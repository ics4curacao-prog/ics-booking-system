"""
Customer Properties + Per-Property Pricing module
==================================================

Drop-in module for the ICS booking system. Adds:

    - Property management (1 customer : many properties)
    - Property images (many photos per property)
    - Contact photo (one photo per user/contact)
    - Per-property service price overrides
    - Price resolution helper (property override -> standard price)

Integration in api.py: see INTEGRATION.md.

This module reuses api.py's get_db / token_required / admin_required via
the register() entry point — it does NOT duplicate auth or DB helpers.
"""

import os
import uuid
from functools import wraps

from flask import request, jsonify, send_from_directory


# ============================================================
# Configuration
# ============================================================
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_IMAGE_SIZE     = 5 * 1024 * 1024   # 5 MB

# Injected by register()
_get_db          = None
_token_required  = None
_admin_required  = None
_upload_folder   = None
_logger          = None


# ============================================================
# Schema migration  (idempotent — safe to run on every boot)
# ============================================================
def run_migrations(get_db_fn, logger=None):
    """Add customer/property/pricing columns + tables.

    Call this from your existing run_migrations() in api.py, AFTER the
    existing booking/resource migrations. Idempotent.
    """
    log = logger or _NoopLogger()
    conn = get_db_fn()
    cursor = conn.cursor()

    # --- users: add customer-facing columns (address already exists) ---
    cursor.execute("PRAGMA table_info(users)")
    user_cols = [c[1] for c in cursor.fetchall()]

    for col, col_type in [
        ("customer_name", "TEXT"),    # company name OR individual's full name
        ("customer_type", "TEXT"),    # 'company' or 'individual'
        ("photo_path",    "TEXT"),    # relative path under UPLOAD_FOLDER
    ]:
        if col not in user_cols:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
            log.info(f"Customer schema: added users.{col}")

    # --- properties ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS properties (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL,
            label          TEXT,
            street_address TEXT NOT NULL,
            city           TEXT,
            country        TEXT DEFAULT 'Curaçao',
            notes          TEXT,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_properties_user_id ON properties(user_id)")

    # --- property_images ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS property_images (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id   INTEGER NOT NULL,
            image_path    TEXT NOT NULL,
            caption       TEXT,
            display_order INTEGER DEFAULT 0,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_property_images_property_id ON property_images(property_id)")

    # --- property_pricing (per-property service price overrides) ---
    # Foreign keys to service_pricing.id (stable) — NOT service name (mutable).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS property_pricing (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id  INTEGER NOT NULL,
            service_id   INTEGER NOT NULL,
            agreed_price REAL    NOT NULL,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(property_id, service_id),
            FOREIGN KEY (property_id) REFERENCES properties(id)       ON DELETE CASCADE,
            FOREIGN KEY (service_id)  REFERENCES service_pricing(id)  ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_property_pricing_property_id ON property_pricing(property_id)")

    # --- bookings: link to customer + property (legacy text fields stay) ---
    cursor.execute("PRAGMA table_info(bookings)")
    booking_cols = [c[1] for c in cursor.fetchall()]
    for col in ["user_id", "property_id"]:
        if col not in booking_cols:
            cursor.execute(f"ALTER TABLE bookings ADD COLUMN {col} INTEGER")
            log.info(f"Customer schema: added bookings.{col}")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_user_id ON bookings(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_property_id ON bookings(property_id)")

    conn.commit()
    conn.close()
    log.info("Customer schema migrations complete")


class _NoopLogger:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


# ============================================================
# Price resolution
# ============================================================
def resolve_property_prices(property_id):
    """Return effective prices for a property as a list of service dicts.

    For each service in service_pricing, returns:
        {
          'id': int,            # service_pricing.id
          'service_name': str,
          'unit': str,
          'category': str,
          'base_price': float,        # standard price
          'agreed_price': float|None, # override if set, else None
          'effective_price': float    # agreed_price if set else base_price
        }

    Use this in the booking flow to compute totals, in the customer portal
    to show agreed rates, and in the invoice generator.
    """
    conn = _get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            sp.id, sp.service_name, sp.base_price, sp.unit, sp.category, sp.is_active,
            pp.agreed_price
        FROM service_pricing sp
        LEFT JOIN property_pricing pp
               ON pp.service_id = sp.id AND pp.property_id = ?
        WHERE sp.is_active = 1
        ORDER BY sp.display_order, sp.id
    """, (property_id,))
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        agreed = r["agreed_price"]
        result.append({
            "id":              r["id"],
            "service_name":    r["service_name"],
            "base_price":      r["base_price"],
            "unit":            r["unit"],
            "category":        r["category"],
            "agreed_price":    agreed,
            "effective_price": agreed if agreed is not None else r["base_price"],
        })
    return result


def resolve_price_for_service(property_id, service_id):
    """Get the effective price for one service on one property.

    Returns float — the agreed price if set, else the standard base_price.
    Raises ValueError if service_id doesn't exist or is inactive.
    """
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sp.base_price, pp.agreed_price
        FROM service_pricing sp
        LEFT JOIN property_pricing pp
               ON pp.service_id = sp.id AND pp.property_id = ?
        WHERE sp.id = ? AND sp.is_active = 1
    """, (property_id, service_id))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise ValueError(f"Service id {service_id} not found or inactive")
    return row["agreed_price"] if row["agreed_price"] is not None else row["base_price"]


# ============================================================
# File helpers
# ============================================================
def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _save_image(file_storage, subfolder, owner_id):
    """Save uploaded file; returns (relative_path, None) or (None, error)."""
    if not file_storage or not file_storage.filename:
        return None, "No file provided"
    if not _allowed(file_storage.filename):
        return None, "Invalid file type. Allowed: jpg, jpeg, png, webp"

    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > MAX_IMAGE_SIZE:
        return None, f"File too large. Max size: {MAX_IMAGE_SIZE // (1024 * 1024)} MB"

    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    target_dir  = os.path.join(_upload_folder, subfolder, str(owner_id))
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, unique_name)
    file_storage.save(target_path)

    rel_path = os.path.relpath(target_path, _upload_folder)
    return rel_path.replace(os.sep, "/"), None


def _delete_file(rel_path):
    if not rel_path:
        return
    try:
        os.remove(os.path.join(_upload_folder, rel_path))
    except OSError:
        pass


# ============================================================
# Route registration
# ============================================================
def register(app, get_db, token_required, admin_required,
             upload_folder="/data/uploads", logger=None):
    """Register all property/image/pricing routes on the given Flask app.

    Call this AFTER you've defined get_db, token_required, admin_required
    in api.py, and after init_database() / run_migrations() have run.

        import customer_properties
        customer_properties.register(
            app, get_db, token_required, admin_required,
            upload_folder=os.path.join(DATABASE_DIR, 'uploads'),
            logger=logger,
        )
    """
    global _get_db, _token_required, _admin_required, _upload_folder, _logger
    _get_db         = get_db
    _token_required = token_required
    _admin_required = admin_required
    _upload_folder  = upload_folder
    _logger         = logger or _NoopLogger()

    os.makedirs(_upload_folder, exist_ok=True)

    # -------------------- helpers using injected current_user --------------------
    def _is_admin(current_user):
        return current_user.get("role") == "admin"

    def _uid(current_user):
        return current_user.get("user_id")

    # ====================================================================
    # PROPERTIES
    # ====================================================================
    @app.route("/api/properties", methods=["GET"])
    @token_required
    def list_properties(current_user):
        conn = get_db()
        cursor = conn.cursor()
        try:
            if _is_admin(current_user):
                uid = request.args.get("user_id", type=int)
                if uid:
                    cursor.execute(
                        "SELECT * FROM properties WHERE user_id = ? ORDER BY created_at DESC",
                        (uid,),
                    )
                else:
                    cursor.execute("SELECT * FROM properties ORDER BY created_at DESC")
            else:
                cursor.execute(
                    "SELECT * FROM properties WHERE user_id = ? ORDER BY created_at DESC",
                    (_uid(current_user),),
                )
            rows = cursor.fetchall()

            result = []
            for r in rows:
                prop = dict(r)
                cursor.execute(
                    "SELECT id, image_path, caption, display_order "
                    "FROM property_images WHERE property_id = ? "
                    "ORDER BY display_order, id",
                    (r["id"],),
                )
                prop["images"] = [dict(i) for i in cursor.fetchall()]
                result.append(prop)
            return jsonify(result)
        finally:
            conn.close()

    @app.route("/api/properties", methods=["POST"])
    @token_required
    def create_property(current_user):
        data = request.json or {}
        target_user_id = data.get("user_id") if _is_admin(current_user) else _uid(current_user)
        if not target_user_id:
            return jsonify({"success": False, "message": "user_id is required"}), 400

        street = (data.get("street_address") or "").strip()
        if not street:
            return jsonify({"success": False, "message": "street_address is required"}), 400

        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO properties (user_id, label, street_address, city, country, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                target_user_id,
                data.get("label"),
                street,
                data.get("city"),
                data.get("country", "Curaçao"),
                data.get("notes"),
            ))
            new_id = cursor.lastrowid
            conn.commit()
            cursor.execute("SELECT * FROM properties WHERE id = ?", (new_id,))
            return jsonify(dict(cursor.fetchone())), 201
        finally:
            conn.close()

    @app.route("/api/properties/<int:prop_id>", methods=["GET"])
    @token_required
    def get_property(current_user, prop_id):
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM properties WHERE id = ?", (prop_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({"success": False, "message": "Property not found"}), 404
            if not _is_admin(current_user) and row["user_id"] != _uid(current_user):
                return jsonify({"success": False, "message": "Forbidden"}), 403

            prop = dict(row)
            cursor.execute(
                "SELECT id, image_path, caption, display_order "
                "FROM property_images WHERE property_id = ? "
                "ORDER BY display_order, id",
                (prop_id,),
            )
            prop["images"] = [dict(i) for i in cursor.fetchall()]
            return jsonify(prop)
        finally:
            conn.close()

    @app.route("/api/properties/<int:prop_id>", methods=["PUT"])
    @token_required
    def update_property(current_user, prop_id):
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT user_id FROM properties WHERE id = ?", (prop_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({"success": False, "message": "Property not found"}), 404
            if not _is_admin(current_user) and row["user_id"] != _uid(current_user):
                return jsonify({"success": False, "message": "Forbidden"}), 403

            data = request.json or {}
            cursor.execute("""
                UPDATE properties SET
                    label          = COALESCE(?, label),
                    street_address = COALESCE(?, street_address),
                    city           = COALESCE(?, city),
                    country        = COALESCE(?, country),
                    notes          = COALESCE(?, notes)
                WHERE id = ?
            """, (
                data.get("label"),
                data.get("street_address"),
                data.get("city"),
                data.get("country"),
                data.get("notes"),
                prop_id,
            ))
            conn.commit()
            cursor.execute("SELECT * FROM properties WHERE id = ?", (prop_id,))
            return jsonify(dict(cursor.fetchone()))
        finally:
            conn.close()

    @app.route("/api/properties/<int:prop_id>", methods=["DELETE"])
    @token_required
    @admin_required
    def delete_property(current_user, prop_id):
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT image_path FROM property_images WHERE property_id = ?",
                (prop_id,),
            )
            imgs = [r["image_path"] for r in cursor.fetchall()]
            cursor.execute("DELETE FROM properties WHERE id = ?", (prop_id,))  # cascades
            conn.commit()
        finally:
            conn.close()
        for p in imgs:
            _delete_file(p)
        return jsonify({"success": True, "message": "Property deleted"})

    # ====================================================================
    # PROPERTY IMAGES
    # ====================================================================
    @app.route("/api/properties/<int:prop_id>/images", methods=["POST"])
    @token_required
    def upload_property_image(current_user, prop_id):
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT user_id FROM properties WHERE id = ?", (prop_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({"success": False, "message": "Property not found"}), 404
            if not _is_admin(current_user) and row["user_id"] != _uid(current_user):
                return jsonify({"success": False, "message": "Forbidden"}), 403

            if "file" not in request.files:
                return jsonify({"success": False, "message": "No file uploaded (expected field 'file')"}), 400

            rel_path, err = _save_image(request.files["file"], "properties", prop_id)
            if err:
                return jsonify({"success": False, "message": err}), 400

            caption = request.form.get("caption", "")
            cursor.execute(
                "SELECT COALESCE(MAX(display_order), -1) AS m FROM property_images WHERE property_id = ?",
                (prop_id,),
            )
            max_order = cursor.fetchone()["m"]

            cursor.execute("""
                INSERT INTO property_images (property_id, image_path, caption, display_order)
                VALUES (?, ?, ?, ?)
            """, (prop_id, rel_path, caption, max_order + 1))
            img_id = cursor.lastrowid
            conn.commit()
            cursor.execute("SELECT * FROM property_images WHERE id = ?", (img_id,))
            return jsonify(dict(cursor.fetchone())), 201
        finally:
            conn.close()

    @app.route("/api/property-images/<int:img_id>", methods=["DELETE"])
    @token_required
    def delete_property_image(current_user, img_id):
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT pi.id, pi.image_path, p.user_id
                FROM property_images pi
                JOIN properties p ON p.id = pi.property_id
                WHERE pi.id = ?
            """, (img_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({"success": False, "message": "Image not found"}), 404
            if not _is_admin(current_user) and row["user_id"] != _uid(current_user):
                return jsonify({"success": False, "message": "Forbidden"}), 403

            cursor.execute("DELETE FROM property_images WHERE id = ?", (img_id,))
            conn.commit()
        finally:
            conn.close()
        _delete_file(row["image_path"])
        return jsonify({"success": True, "message": "Image deleted"})

    # ====================================================================
    # CONTACT PHOTO  (one per user)
    # ====================================================================
    @app.route("/api/users/<int:user_id>/photo", methods=["POST"])
    @token_required
    def upload_contact_photo(current_user, user_id):
        if not _is_admin(current_user) and _uid(current_user) != user_id:
            return jsonify({"success": False, "message": "Forbidden"}), 403
        if "file" not in request.files:
            return jsonify({"success": False, "message": "No file uploaded (expected field 'file')"}), 400

        rel_path, err = _save_image(request.files["file"], "contacts", user_id)
        if err:
            return jsonify({"success": False, "message": err}), 400

        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT photo_path FROM users WHERE id = ?", (user_id,))
            old = cursor.fetchone()
            if old and old["photo_path"]:
                _delete_file(old["photo_path"])
            cursor.execute("UPDATE users SET photo_path = ? WHERE id = ?", (rel_path, user_id))
            conn.commit()
        finally:
            conn.close()
        return jsonify({"success": True, "photo_path": rel_path}), 201

    # ====================================================================
    # PER-PROPERTY PRICING
    # ====================================================================
    @app.route("/api/properties/<int:prop_id>/prices", methods=["GET"])
    @token_required
    def get_property_prices(current_user, prop_id):
        """Return all services with effective prices for this property."""
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT user_id FROM properties WHERE id = ?", (prop_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({"success": False, "message": "Property not found"}), 404
            if not _is_admin(current_user) and row["user_id"] != _uid(current_user):
                return jsonify({"success": False, "message": "Forbidden"}), 403
        finally:
            conn.close()
        return jsonify(resolve_property_prices(prop_id))

    @app.route("/api/properties/<int:prop_id>/prices", methods=["PUT"])
    @token_required
    @admin_required
    def upsert_property_prices(current_user, prop_id):
        """Bulk-set agreed prices for a property.

        Expected JSON body:
            { "prices": [ { "service_id": 1, "agreed_price": 90.00 }, ... ] }

        Rules:
            - agreed_price = null OR omitted entry  -> remove override (revert to standard)
            - agreed_price = number                 -> insert or update override
            - Services not mentioned are left unchanged.
        """
        data = request.json or {}
        prices = data.get("prices", [])
        if not isinstance(prices, list):
            return jsonify({"success": False, "message": "'prices' must be a list"}), 400

        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM properties WHERE id = ?", (prop_id,))
            if not cursor.fetchone():
                return jsonify({"success": False, "message": "Property not found"}), 404

            for item in prices:
                service_id   = item.get("service_id")
                agreed_price = item.get("agreed_price")
                if service_id is None:
                    continue

                if agreed_price is None:
                    cursor.execute(
                        "DELETE FROM property_pricing WHERE property_id = ? AND service_id = ?",
                        (prop_id, service_id),
                    )
                else:
                    cursor.execute("""
                        INSERT INTO property_pricing (property_id, service_id, agreed_price)
                        VALUES (?, ?, ?)
                        ON CONFLICT(property_id, service_id)
                        DO UPDATE SET agreed_price = excluded.agreed_price,
                                      updated_at   = CURRENT_TIMESTAMP
                    """, (prop_id, service_id, float(agreed_price)))
            conn.commit()
        finally:
            conn.close()

        _logger.info(f"Property {prop_id} pricing updated by user {_uid(current_user)}")
        return jsonify({"success": True, "prices": resolve_property_prices(prop_id)})

    @app.route("/api/properties/<int:prop_id>/prices/<int:service_id>", methods=["DELETE"])
    @token_required
    @admin_required
    def delete_property_price(current_user, prop_id, service_id):
        """Remove one override; service reverts to standard price."""
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "DELETE FROM property_pricing WHERE property_id = ? AND service_id = ?",
                (prop_id, service_id),
            )
            conn.commit()
        finally:
            conn.close()
        return jsonify({"success": True, "message": "Override removed"})

    # ====================================================================
    # STATIC FILE SERVING
    # ====================================================================
    @app.route("/uploads/<path:filename>")
    def serve_upload(filename):
        return send_from_directory(_upload_folder, filename)

    _logger.info("Customer properties routes registered")
