import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import random
import json
app = Flask(__name__)

# === КОНФІГУРАЦІЯ ДЛЯ ЗАВАНТАЖЕННЯ ФОТО ===
UPLOAD_FOLDER = os.path.join('static', 'images', 'products')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

app.config['SECRET_KEY'] = 'shop_secret_key_2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:1111@localhost/store'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

@app.route('/')
def index():
    promos = db.session.execute(text("SELECT * FROM promotion WHERE is_active = 1 LIMIT 3")).mappings().all()

    # Поліпшене завантаження товарів для головної — ТІЛЬКИ з наявністю
    products_raw = db.session.execute(text("""
        SELECT p.*,
               AVG(CASE WHEN r.is_hidden = 0 OR r.is_hidden IS NULL THEN r.rating END) as avg_rating,
               COUNT(CASE WHEN r.is_hidden = 0 OR r.is_hidden IS NULL THEN r.id_review END) as review_count
        FROM product p
        LEFT JOIN review r ON p.id_product = r.id_product
        WHERE p.stock > 0
        GROUP BY p.id_product
        ORDER BY p.id_product DESC 
        LIMIT 8
    """)).mappings().all()

    products = []
    for row in products_raw:
        p = dict(row)

        # Завантажуємо перше фото
        images = db.session.execute(text("""
            SELECT filename
            FROM product_image
            WHERE id_product = :pid
            ORDER BY is_main DESC, sort_order ASC LIMIT 1
        """), {"pid": p['id_product']}).mappings().all()

        p['images'] = [dict(img) for img in images]
        products.append(p)

    return render_template('index.html', products=products, promos=promos)


@app.route('/about')
def about():
    return render_template('about.html')


# ==========================================
# КАТАЛОГ З ІЄРАРХІЄЮ
# ==========================================

@app.route('/catalog')
def catalog():
    # Головні категорії
    main_categories_raw = db.session.execute(text("""
        SELECT c.*, 
               COUNT(DISTINCT p.id_product) as product_count
        FROM category c
        LEFT JOIN subcategory s ON c.id_category = s.id_category
        LEFT JOIN product p ON s.id_subcategory = p.id_subcategory 
                           AND p.stock > 0                    -- ← ВАЖЛИВО
        GROUP BY c.id_category
        ORDER BY c.name
    """)).mappings().all()

    # Підкатегорії
    subcategories_raw = db.session.execute(text("""
        SELECT s.*,
               c.id_category as category_id,
               COUNT(p.id_product) as product_count
        FROM subcategory s
        JOIN category c ON s.id_category = c.id_category
        LEFT JOIN product p ON s.id_subcategory = p.id_subcategory 
                           AND p.stock > 0                    -- ← ВАЖЛИВО
        GROUP BY s.id_subcategory
        ORDER BY s.name
    """)).mappings().all()

    # Товари + фото + характеристики + id_category
    products_raw = db.session.execute(text("""
        SELECT p.*,
               c.id_category,
               c.name as category_name,
               s.name as subcategory_name,
               AVG(CASE WHEN r.is_hidden = 0 OR r.is_hidden IS NULL THEN r.rating END) as avg_rating,
               COUNT(CASE WHEN r.is_hidden = 0 OR r.is_hidden IS NULL THEN r.id_review END) as review_count
        FROM product p
        LEFT JOIN subcategory s ON p.id_subcategory = s.id_subcategory
        LEFT JOIN category c ON s.id_category = c.id_category
        LEFT JOIN review r ON p.id_product = r.id_product
        WHERE p.stock > 0                    -- ← Головне виправлення
        GROUP BY p.id_product, c.id_category, s.name, c.name
        ORDER BY p.id_product DESC
    """)).mappings().all()
    products = []
    for row in products_raw:
        p = dict(row)

        # Конвертація типів для запобігання помилок сортування та фільтрації у JS
        p['base_price'] = float(p['base_price'] or 0)
        p['avg_rating'] = float(p['avg_rating']) if p['avg_rating'] else 0
        p['review_count'] = int(p['review_count'] or 0)

        # Фото
        images = db.session.execute(text("""
                                         SELECT filename
                                         FROM product_image
                                         WHERE id_product = :pid
                                         ORDER BY is_main DESC, sort_order ASC
                                         """), {"pid": p['id_product']}).mappings().all()
        p['images'] = [dict(img) for img in images]

        # Характеристики (EAV) — витягуємо attr_name та value
        attrs = db.session.execute(text("""
                                        SELECT a.attr_name, pav.value
                                        FROM product_attribute_value pav
                                                 JOIN attribute a ON pav.id_attribute = a.id_attribute
                                        WHERE pav.id_product = :pid
                                        """), {"pid": p['id_product']}).mappings().all()
        p['attributes'] = [dict(a) for a in attrs]

        products.append(p)

    return render_template('catalog.html',
                           main_categories=[dict(row) for row in main_categories_raw],
                           subcategories=[dict(row) for row in subcategories_raw],
                           products=products)
@app.route('/subcategory/<int:sub_id>')
def subcategory_page(sub_id):
    """Сторінка товарів конкретної підкатегорії"""
    subcategory = db.session.execute(text("""
                                          SELECT s.*, c.name as category_name, c.id_category
                                          FROM subcategory s
                                                   JOIN category c ON s.id_category = c.id_category
                                          WHERE s.id_subcategory = :id
                                          """), {"id": sub_id}).mappings().first()

    if not subcategory:
        flash("Підкатегорія не знайдена", "danger")
        return redirect(url_for('catalog'))

    products_raw = db.session.execute(text("""
        SELECT p.*,
               c.id_category,
               c.name as category_name,
               s.name as subcategory_name,
               AVG(CASE WHEN r.is_hidden = 0 OR r.is_hidden IS NULL THEN r.rating END) as avg_rating,
               COUNT(CASE WHEN r.is_hidden = 0 OR r.is_hidden IS NULL THEN r.id_review END) as review_count
        FROM product p
        LEFT JOIN subcategory s ON p.id_subcategory = s.id_subcategory
        LEFT JOIN category c ON s.id_category = c.id_category
        LEFT JOIN review r ON p.id_product = r.id_product
        WHERE p.stock > 0                    -- ← Головне виправлення
        GROUP BY p.id_product, c.id_category, s.name, c.name
        ORDER BY p.id_product DESC
    """)).mappings().all()

    products = []
    for row in products_raw:
        p = dict(row)

        # Завантажуємо фото
        images = db.session.execute(text("""
                                         SELECT id_image, filename
                                         FROM product_image
                                         WHERE id_product = :pid
                                         ORDER BY is_main DESC, sort_order ASC
                                         """), {"pid": p['id_product']}).mappings().all()

        p['images'] = [dict(img) for img in images]

        products.append(p)

    return render_template('subcategory.html',
                           subcategory=dict(subcategory),
                           products=products)


@app.route('/product/<int:pid>')
def product_page(pid):
    product = db.session.execute(text("""
                                      SELECT p.*,
                                             AVG(CASE WHEN r.is_hidden = 0 OR r.is_hidden IS NULL THEN r.rating END)      as avg_rating,
                                             COUNT(CASE WHEN r.is_hidden = 0 OR r.is_hidden IS NULL THEN r.id_review END) as review_count
                                      FROM product p
                                               LEFT JOIN review r ON p.id_product = r.id_product
                                      WHERE p.id_product = :id
                                      GROUP BY p.id_product
                                      """), {"id": pid}).mappings().first()

    if not product:
        flash("Товар не знайдено", "danger")
        return redirect(url_for('catalog'))

    # Фото
    images = db.session.execute(text("""
                                     SELECT filename
                                     FROM product_image
                                     WHERE id_product = :pid
                                     ORDER BY is_main DESC, sort_order ASC
                                     """), {"pid": pid}).mappings().all()

    # Характеристики
    attrs_raw = db.session.execute(text("""
                                        SELECT a.attr_name, pav.value
                                        FROM product_attribute_value pav
                                                 JOIN attribute a ON pav.id_attribute = a.id_attribute
                                        WHERE pav.id_product = :id
                                        """), {"id": pid}).mappings().all()

    product_dict = dict(product)
    product_dict['images'] = [dict(img) for img in images]

    return render_template('product_detail.html',
                           product=product_dict,
                           attrs=[dict(a) for a in attrs_raw])


@app.route('/promotions')
def promotions():
    promos = db.session.execute(text("SELECT * FROM promotion WHERE is_active = 1")).mappings().all()
    return render_template('promotions.html', promos=promos)


@app.route('/favorites')
def favorites():
    if 'user_id' not in session:
        # Якщо користувач не залогінений — показуємо порожню сторінку або повідомлення
        return render_template('favorites.html', favorites=[])

    # Отримуємо id товарів, які користувач додав в улюблені
    # Використовуємо .mappings().all() для зручного доступу за назвами колонок
    fav_ids_raw = db.session.execute(text("""
        SELECT id_product
        FROM favorite
        WHERE id_user = :uid
    """), {'uid': session.get('user_id')}).mappings().all()

    # Створюємо чистий список ідентифікаторів
    fav_ids = [row['id_product'] for row in fav_ids_raw]

    # ВИПРАВЛЕННЯ: Якщо список ідентифікаторів порожній,
    # одразу повертаємо порожній шаблон БЕЗ виконання SQL-запиту з "IN ()"
    if not fav_ids:
        return render_template('favorites.html', favorites=[])

    # Завантажуємо товари з фото, рейтингом і характеристиками
    # Передаємо fav_ids як tuple, щоб SQLAlchemy коректно розгорнув його в SQL-конструкцію IN (1, 2, 3)
    products_raw = db.session.execute(text("""
        SELECT p.*,
               AVG(CASE WHEN r.is_hidden = 0 OR r.is_hidden IS NULL THEN r.rating END) as avg_rating,
               COUNT(CASE WHEN r.is_hidden = 0 OR r.is_hidden IS NULL THEN r.id_review END) as review_count
        FROM product p
        LEFT JOIN review r ON p.id_product = r.id_product
        WHERE p.id_product IN :ids
        GROUP BY p.id_product
        ORDER BY p.id_product DESC
    """), {"ids": tuple(fav_ids)}).mappings().all()

    favorites = []
    for row in products_raw:
        p = dict(row)

        p['base_price'] = float(p['base_price'] or 0)
        p['avg_rating'] = float(p['avg_rating']) if p['avg_rating'] else 0
        p['review_count'] = int(p['review_count'] or 0)

        # Фото
        images = db.session.execute(text("""
            SELECT filename
            FROM product_image
            WHERE id_product = :pid
            ORDER BY is_main DESC, sort_order ASC LIMIT 1
        """), {"pid": p['id_product']}).mappings().all()

        p['images'] = [dict(img) for img in images]

        favorites.append(p)

    return render_template('favorites.html', favorites=favorites)
@app.route('/cart')
def cart():
    return render_template('cart.html')


# ==========================================
# 🛒 ОФОРМЛЕННЯ ЗАМОВЛЕННЯ
# ==========================================

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    # ==========================================
    # 1. ВІДОБРАЖЕННЯ СТОРІНКИ (GET-запит)
    # ==========================================
    if request.method == 'GET':
        return render_template('checkout.html')

    # ==========================================
    # 2. ОБРОБКА ОФОРМЛЕННЯ ЗАМОВЛЕННЯ (POST-запит)
    # ==========================================
    full_name = request.form.get('full_name')
    phone = request.form.get('phone')
    email = request.form.get('email')

    delivery_method = request.form.get('delivery_method')
    delivery_address = request.form.get('delivery_address')
    payment_method = request.form.get('payment_method')
    cart_json = request.form.get('cart_data')

    if not cart_json:
        flash("Кошик порожній або дані замовлення втрачені.", "danger")
        return redirect(url_for('cart'))

    try:
        cart_items = json.loads(cart_json)
    except Exception:
        flash("Помилка під час обробки товарів у кошику.", "danger")
        return redirect(url_for('cart'))

    current_user_id = session.get('user_id')
    create_account = request.form.get('create_account')
    password = request.form.get('password')

    if not current_user_id and create_account == 'yes' and password:
        existing_user = db.session.execute(
            text("SELECT id_user FROM user WHERE email = :email"), {'email': email}
        ).fetchone()

        if not existing_user:
            hashed_pwd = generate_password_hash(password)
            db.session.execute(
                text("""
                     INSERT INTO user (full_name, email, phone, password_hash)
                     VALUES (:name, :email, :phone, :pwd)
                     """),
                {'name': full_name, 'email': email, 'phone': phone, 'pwd': hashed_pwd}
            )
            db.session.commit()

            new_user = db.session.execute(
                text("SELECT id_user FROM user WHERE email = :email"), {'email': email}
            ).fetchone()
            if new_user:
                current_user_id = new_user[0]
                session['user_id'] = current_user_id
                session['full_name'] = full_name

    # Якщо замовлення робить гість і не реєструється, тимчасово прив'язуємо замовлення до id_user = 1 (або залиште NULL, якщо БД дозволяє)
    # Зверніть увагу: у вашій структурі `id_user` INT NOT NULL, тому для гостей потрібен існуючий дефолтний користувач, або робимо id_user = 1
    if not current_user_id:
        current_user_id = 1

    # Рахуємо фінальну суму
    total_amount = 0
    for item in cart_items:
        total_amount += float(item.get('price', 0)) * int(item.get('quantity', 1))

    # Відображаємо методи доставки на id_delivery з вашої бази:
    # Припустимо: 1 - Самовивіз, 2 - Нова Пошта, 3 - Кур'єр
    id_delivery = 1
    if delivery_method == 'nova_poshta':
        id_delivery = 2
    elif delivery_method == 'courier':
        id_delivery = 3

    # Формуємо красивий рядок адреси, куди додаємо інформацію про спосіб оплати/доставки/ТТН
    random_ttn = f"204500{random.randint(100000, 999999)}"
    extended_address = f"Спосіб отримання: {delivery_method}. Адреса: {delivery_address}. Оплата: {payment_method}."
    if delivery_method == 'nova_poshta':
        extended_address += f" Згенеровано ТТН: {random_ttn}"

    # === ВИПРАВЛЕНИЙ ЗАПИТ: Використовуємо реальну таблицю `order` та її колонки ===
    db.session.execute(
        text("""
             INSERT INTO `order` (id_user, order_date, delivery_address, is_paid, total_amount, status, id_delivery)
             VALUES (:id_user, NOW(), :delivery_address, :is_paid, :total_amount, :status, :id_delivery)
             """),
        {
            'id_user': current_user_id,
            'delivery_address': extended_address,
            'is_paid': 1 if payment_method == 'card' else 0,
            'total_amount': total_amount,
            'status': 'В обробці',
            'id_delivery': id_delivery
        }
    )
    db.session.commit()

    # Отримуємо ID останнього створеного замовлення для поточного користувача
    created_order = db.session.execute(
        text("""
             SELECT id_order FROM `order` 
             WHERE id_user = :id_user 
             ORDER BY id_order DESC LIMIT 1
             """),
        {'id_user': current_user_id}
    ).fetchone()

    if created_order:
        id_order = created_order[0]
        # Переносимо товари в order_item (структура повністю збігається!)
        for item in cart_items:
            db.session.execute(
                text("""
                     INSERT INTO order_item (id_order, id_product, quantity, price_at_time)
                     VALUES (:id_order, :id_prod, :qty, :price)
                     """),
                {
                    'id_order': id_order,
                    'id_prod': item.get('id'),
                    'qty': item.get('quantity'),
                    'price': item.get('price')
                }
            )
        db.session.commit()

    # Замість випадкового тексту передаємо id_order як номер замовлення
    if payment_method == 'card':
        return redirect(url_for('payment_page', order_no=id_order))
    else:
        return redirect(url_for('order_complete', order_no=id_order, status='success'))

@app.route('/payment/<int:order_no>')
def payment_page(order_no):
    order = db.session.execute(text("""
                                    SELECT id_order, total_amount, status
                                    FROM `order`
                                    WHERE id_order = :order_no
                                    """), {"order_no": order_no}).mappings().first()

    if not order:
        flash("Замовлення не знайдено", "danger")
        return redirect(url_for('profile'))

    return render_template('payment.html',
                           order_no=order_no,
                           total_amount=order['total_amount'])


@app.route('/order_complete')
def order_complete():
    order_no = request.args.get('order_no', '—')
    status = request.args.get('status', 'success')

    ttn = None
    pickup_time = None

    # === ВИПРАВЛЕНО: Перевіряємо спосіб доставки із створеного замовлення ===
    if order_no != '—' and status == 'success':
        order = db.session.execute(text("""
                                        SELECT delivery_address
                                        FROM `order`
                                        WHERE id_order = :id
                                        """), {"id": order_no}).mappings().first()

        if order:
            address = order['delivery_address']
            # Якщо в адресі фігурує Нова Пошта — виводимо ТТН
            if "Нова Пошта" in address:
                ttn = f"NP{random.randint(100000000, 999999999)}"
            # Якщо Самовивіз — виводимо тільки інформацію про самовивіз
            elif "Самовивіз" in address:
                pickup_time = "Завтра з 10:00 до 18:00 (Магазин працює без вихідних)"

    return render_template('order_complete.html',
                           order_no=order_no,
                           status=status,
                           ttn=ttn,
                           pickup_time=pickup_time)


# ==========================================
# 👤 АВТОРИЗАЦІЯ
# ==========================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = db.session.execute(text("SELECT * FROM user WHERE email = :e"), {"e": email}).mappings().first()

        if user:
            password_hash = user.get('password_hash') or ''
            if (password_hash and check_password_hash(password_hash, password)) or password_hash == password:
                session.update({
                    'user_id': user['id_user'],
                    'role': user['role'],
                    'full_name': user['full_name']
                })
                flash(f"Вітаємо, {user['full_name']}!", "success")
                return redirect(url_for('admin_main') if user['role'] == 1 else url_for('profile'))

        flash("Невірний email або пароль", "danger")

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        pw_hash = generate_password_hash(request.form.get('password'))
        try:
            db.session.execute(text("""
                                    INSERT INTO user (full_name, phone, email, password_hash, city, saved_address, role)
                                    VALUES (:n, :phone, :e, :h, :city, :address, 0)
                                    """), {
                                   "n": request.form.get('full_name'),
                                   "phone": request.form.get('phone'),
                                   "e": request.form.get('email'),
                                   "h": pw_hash,
                                   "city": request.form.get('city'),
                                   "address": request.form.get('saved_address')
                               })
            db.session.commit()
            flash("Реєстрація успішна! Увійдіть.", "success")
            return redirect(url_for('login'))
        except:
            db.session.rollback()
            flash("Такий email вже зареєстрований", "danger")

    return render_template('register.html')


@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = db.session.execute(text("SELECT * FROM user WHERE id_user = :uid"),
                              {"uid": session['user_id']}).mappings().first()
    orders = db.session.execute(text("SELECT * FROM `order` WHERE id_user = :uid ORDER BY order_date DESC"),
                                {"uid": session['user_id']}).mappings().all()

    return render_template('profile.html', user=user, orders=orders)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ==========================================
# 🛠️ АДМІН-ПАНЕЛЬ
# ==========================================

@app.route('/admin')
def admin_redirect():
    return redirect(url_for('admin_main'))


@app.route('/admin/main')
def admin_main():
    if session.get('role') != 1:
        return redirect(url_for('login'))

    stats = get_admin_stats()

    # Останні замовлення
    recent_orders = db.session.execute(text("""
                                            SELECT o.id_order,
                                                   o.order_date,
                                                   o.total_amount,
                                                   o.status,
                                                   u.full_name as user_name
                                            FROM `order` o
                                                     JOIN user u ON o.id_user = u.id_user
                                            ORDER BY o.order_date DESC LIMIT 5
                                            """)).mappings().all()

    return render_template('admin/admin_main.html',
                           stats=stats,
                           recent_orders=recent_orders)


@app.route('/admin/products')
def admin_products():
    if session.get('role') != 1:
        return redirect(url_for('login'))

    sort = request.args.get('sort', 'id_desc')
    sort_options = {
        'name_asc': 'p.name ASC',
        'name_desc': 'p.name DESC',
        'price_asc': 'p.base_price ASC',
        'price_desc': 'p.base_price DESC',
        'stock_asc': 'p.stock ASC',
        'stock_desc': 'p.stock DESC',
        'id_desc': 'p.id_product DESC'
    }
    order_by = sort_options.get(sort, 'p.id_product DESC')

    products_raw = db.session.execute(text(f"""
        SELECT p.*, 
               s.name as subcategory_name, 
               c.name as category_name,
               COALESCE(p.stock, 0) as stock
        FROM product p
        LEFT JOIN subcategory s ON p.id_subcategory = s.id_subcategory
        LEFT JOIN category c ON s.id_category = c.id_category
        ORDER BY {order_by}
    """)).mappings().all()

    products = []
    for row in products_raw:
        p = dict(row)

        # 1. Завантажуємо фото
        images = db.session.execute(text("""
                                         SELECT id_image as id_image,
                                                filename
                                         FROM product_image
                                         WHERE id_product = :pid
                                         ORDER BY is_main DESC, sort_order ASC
                                         """), {"pid": p['id_product']}).mappings().all()

        p['images'] = [
            {
                'id_image': img.id_image,
                'url': url_for('static', filename=f'images/products/{img.filename}')
            }
            for img in images
        ]

        # 2. Визначаємо id_category на основі підкатегорії товару
        if p.get('id_subcategory'):
            cat_row = db.session.execute(text("""
                                              SELECT id_category
                                              FROM subcategory
                                              WHERE id_subcategory = :sub_id
                                              """), {"sub_id": p['id_subcategory']}).mappings().first()
            p['id_category'] = cat_row['id_category'] if cat_row else None
        else:
            p['id_category'] = None

        # 3. Завантажуємо характеристики для передачі в JS форму редагування
        attr_rows = db.session.execute(text("""
                                            SELECT a.attr_name, pav.value
                                            FROM product_attribute_value pav
                                                     JOIN attribute a ON pav.id_attribute = a.id_attribute
                                            WHERE pav.id_product = :pid
                                            """), {"pid": p['id_product']}).mappings().all()

        p['attributes'] = [dict(a) for a in attr_rows]

        products.append(p)

    main_categories = db.session.execute(text("SELECT * FROM category ORDER BY name")).mappings().all()

    return render_template('admin/products.html',
                           products=products,
                           main_categories=main_categories,
                           stats=get_admin_stats(),
                           current_sort=sort)


def get_admin_stats():
    stats = {
        'orders_count': db.session.execute(
            text("SELECT COUNT(*) FROM `order` WHERE DATE(order_date) = CURDATE()")
        ).scalar() or 0,

        'total_revenue': db.session.execute(
            text("SELECT COALESCE(SUM(total_amount), 0) FROM `order`")
        ).scalar() or 0,

        'users_count': db.session.execute(
            text("SELECT COUNT(*) FROM user WHERE DATE(created_at) = CURDATE()")
        ).scalar() or 0,

        'products_count': db.session.execute(
            text("SELECT COUNT(*) FROM product")
        ).scalar() or 0,

        # === НОВА СТАТИСТИКА — Продані товари за категоріями ===
        'category_stats': db.session.execute(text("""
            SELECT 
                c.name as category_name,
                COALESCE(SUM(oi.quantity), 0) as product_count,   -- кількість проданих одиниць
                COALESCE(SUM(oi.quantity * oi.price_at_time), 0) as revenue
            FROM category c
            LEFT JOIN subcategory s ON c.id_category = s.id_category
            LEFT JOIN product p ON s.id_subcategory = p.id_subcategory
            LEFT JOIN order_item oi ON p.id_product = oi.id_product
            GROUP BY c.id_category, c.name
            ORDER BY product_count DESC, revenue DESC
        """)).mappings().all()
    }
    return stats


@app.route('/admin/save_product', methods=['POST'])
def admin_save_product():
    if session.get('role') != 1:
        return redirect(url_for('login'))

    try:
        pid = request.form.get('id_product')
        pid = int(pid) if pid and pid.isdigit() else None

        name = request.form.get('name')
        price = float(request.form.get('base_price') or 0)
        description = request.form.get('description', '')
        stock = int(request.form.get('stock') or 0)

        # === Категорія та підкатегорія ===
        cat_id = request.form.get('id_category')
        if request.form.get('new_category_name'):
            db.session.execute(text("INSERT INTO category (name) VALUES (:name)"),
                               {"name": request.form.get('new_category_name')})
            db.session.commit()
            cat_id = db.session.execute(text("SELECT LAST_INSERT_ID()")).scalar()

        subcat_id = request.form.get('id_subcategory')
        if request.form.get('new_subcategory_name'):
            db.session.execute(text("INSERT INTO subcategory (name, id_category) VALUES (:name, :cat)"),
                               {"name": request.form.get('new_subcategory_name'), "cat": cat_id or 1})
            db.session.commit()
            subcat_id = db.session.execute(text("SELECT LAST_INSERT_ID()")).scalar()

        if not subcat_id:
            flash("Підкатегорія обов'язкова!", "danger")
            return redirect(url_for('admin_products'))

        # === Видалення фото ===
        delete_images = request.form.get('delete_images', '')
        if delete_images:
            delete_list = [int(x) for x in delete_images.split(',') if x.strip()]
            if delete_list:
                db.session.execute(text("DELETE FROM product_image WHERE id_image IN :ids"),
                                   {"ids": delete_list})

        # === Створення нового товару ===
        if pid is None:
            db.session.execute(text("""
                                    INSERT INTO product (name, base_price, description, id_subcategory, stock)
                                    VALUES (:name, :price, :desc, :subcat, :stock)
                                    """), {
                                   "name": name, "price": price, "desc": description,
                                   "subcat": subcat_id, "stock": stock
                               })
            db.session.commit()
            pid = db.session.execute(text("SELECT LAST_INSERT_ID()")).scalar()

        # === Оновлення/створення характеристик ===
        db.session.execute(text("DELETE FROM product_attribute_value WHERE id_product = :pid"), {"pid": pid})

        attr_names = request.form.getlist('attr_name[]')
        attr_values = request.form.getlist('attr_value[]')

        for name_item, val_item in zip(attr_names, attr_values):
            if name_item.strip() and val_item.strip():
                attr_exist = db.session.execute(
                    text("SELECT id_attribute FROM attribute WHERE attr_name = :name"),
                    {"name": name_item.strip()}
                ).mappings().first()

                if attr_exist:
                    id_attr = attr_exist['id_attribute']
                else:
                    db.session.execute(text("INSERT INTO attribute (attr_name) VALUES (:name)"),
                                       {"name": name_item.strip()})
                    db.session.commit()
                    id_attr = db.session.execute(text("SELECT LAST_INSERT_ID()")).scalar()

                db.session.execute(text("""
                                        INSERT INTO product_attribute_value (id_product, id_attribute, value)
                                        VALUES (:pid, :aid, :val)
                                        """), {
                                       "pid": pid,
                                       "aid": id_attr,
                                       "val": val_item.strip()
                                   })

        # === Додавання нових фото ===
        files = request.files.getlist('images')
        if files and any(f.filename for f in files):
            for i, file in enumerate(files):
                if file and file.filename:
                    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"prod_{pid}_{timestamp}_{i:02d}.{ext}"

                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(file_path)

                    db.session.execute(text("""
                                            INSERT INTO product_image (id_product, filename, is_main, sort_order)
                                            VALUES (:pid, :filename, :is_main, :sort_order)
                                            """), {
                                           "pid": pid,
                                           "filename": filename,
                                           "is_main": 1 if i == 0 else 0,
                                           "sort_order": i
                                       })

        # === Оновлення основних даних товару ===
        db.session.execute(text("""
                                UPDATE product
                                SET name           = :name,
                                    base_price     = :price,
                                    description    = :desc,
                                    id_subcategory = :subcat,
                                    stock          = :stock
                                WHERE id_product = :pid
                                """), {
                               "name": name,
                               "price": price,
                               "desc": description,
                               "subcat": subcat_id,
                               "stock": stock,
                               "pid": pid
                           })

        db.session.commit()
        flash("Товар успішно збережено!", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Помилка збереження: {str(e)}", "danger")

    return redirect(url_for('admin_products'))


@app.route('/admin/subcategories/<int:cat_id>')
def get_subcategories(cat_id):
    subs = db.session.execute(
        text("SELECT id_subcategory as id, name FROM subcategory WHERE id_category = :cid ORDER BY name"),
        {"cid": cat_id}
    ).mappings().all()
    return jsonify([{"id": s.id, "name": s.name} for s in subs])


@app.route('/admin/delete_product/<int:pid>')
def delete_product(pid):
    if session.get('role') != 1:
        return redirect(url_for('login'))
    try:
        db.session.execute(text("DELETE FROM product WHERE id_product = :pid"), {"pid": pid})
        db.session.commit()
        flash("Товар видалено", "success")
    except:
        flash("Не вдалося видалити товар", "danger")
    return redirect(url_for('admin_products'))


@app.route('/admin/promotions', methods=['GET', 'POST'])
def admin_promotions():
    if session.get('role') != 1:
        return redirect(url_for('index'))

    if request.method == 'POST':
        id_promotion = request.form.get('id_promotion')
        name = request.form.get('name')
        discount = request.form.get('discount')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        description = request.form.get('description')

        if id_promotion:
            db.session.execute(
                text("""
                     UPDATE promotion
                     SET name             = :n,
                         discount_percent = :d,
                         start_date       = :sd,
                         end_date         = :ed,
                         description      = :desc
                     WHERE id_promotion = :id
                     """),
                {"n": name, "d": discount, "sd": start_date, "ed": end_date, "desc": description, "id": id_promotion}
            )
            flash("Акцію успешно оновлено!")
        else:
            db.session.execute(
                text("""
                     INSERT INTO promotion (name, discount_percent, start_date, end_date, description, is_active)
                     VALUES (:n, :d, :sd, :ed, :desc, 1)
                     """),
                {"n": name, "d": discount, "sd": start_date, "ed": end_date, "desc": description}
            )
            flash("Акцію додано успішно!")

        db.session.commit()
        return redirect(url_for('admin_promotions'))

    raw_promos = db.session.execute(text("SELECT * FROM promotion ORDER BY id_promotion DESC")).mappings().all()
    promos = [dict(row) for row in raw_promos]

    return render_template('admin/promotions.html', promos=promos, stats=get_admin_stats())


@app.route('/admin/delete_promotion/<int:id>')
def delete_promotion(id):
    db.session.execute(text("DELETE FROM promotion WHERE id_promotion = :id"), {"id": id})
    db.session.commit()
    return redirect(url_for('admin_promotions'))


@app.route('/admin/orders')
def admin_orders():
    if session.get('role') != 1:
        return redirect(url_for('login'))

    sort_by = request.args.get('sort', 'date_desc')

    sort_options = {
        'id_asc': 'o.id_order ASC',
        'id_desc': 'o.id_order DESC',
        'date_asc': 'o.order_date ASC',
        'date_desc': 'o.order_date DESC',
        'client_asc': 'u.full_name ASC',
        'client_desc': 'u.full_name DESC',
        'amount_asc': 'o.total_amount ASC',
        'amount_desc': 'o.total_amount DESC'
    }

    order_clause = sort_options.get(sort_by, 'o.order_date DESC')

    raw_orders = db.session.execute(text(f"""
        SELECT o.*, u.full_name,
               COUNT(oi.id_product) as items_count
        FROM `order` o
        JOIN user u ON o.id_user = u.id_user
        LEFT JOIN order_item oi ON o.id_order = oi.id_order
        GROUP BY o.id_order
        ORDER BY {order_clause}
    """)).mappings().all()

    orders = [dict(row) for row in raw_orders]

    return render_template(
        'admin/orders.html',
        orders=orders,
        current_sort=sort_by,
        stats=get_admin_stats()
    )


@app.route('/admin/users', methods=['GET', 'POST'])
def admin_users():
    if session.get('role') != 1:
        return redirect(url_for('login'))

    sort_by = request.args.get('sort', 'id_desc')

    sort_options = {
        'id_asc': 'id_user ASC',
        'id_desc': 'id_user DESC',
        'name_asc': 'full_name ASC',
        'name_desc': 'full_name DESC',
        'email_asc': 'email ASC',
        'email_desc': 'email DESC',
        'role_asc': 'role ASC',
        'role_desc': 'role DESC'
    }

    order_clause = sort_options.get(sort_by, 'id_user DESC')

    raw_users = db.session.execute(text(f"SELECT * FROM user ORDER BY {order_clause}")).mappings().all()
    users = [dict(row) for row in raw_users]

    user_id = request.args.get('user_id')
    history = []
    selected_user = None
    if user_id:
        u_match = db.session.execute(text("SELECT * FROM user WHERE id_user = :id"), {"id": user_id}).mappings().first()
        if u_match:
            selected_user = dict(u_match)
            raw_history = db.session.execute(
                text("SELECT * FROM `order` WHERE id_user = :id ORDER BY id_order DESC"),
                {"id": user_id}
            ).mappings().all()
            history = [dict(row) for row in raw_history]

    return render_template(
        'admin/users.html',
        users=users,
        history=history,
        selected_user=selected_user,
        current_sort=sort_by,
        stats=get_admin_stats()
    )


@app.route('/admin/users/update_role/<int:id>', methods=['POST'])
def update_user_role(id):
    if session.get('role') != 1:
        return redirect(url_for('login'))

    new_role = request.form.get('role')
    try:
        db.session.execute(
            text("UPDATE user SET role = :role WHERE id_user = :id"),
            {"role": new_role, "id": id}
        )
        db.session.commit()
        flash("Роль користувача успішно змінено!")
    except Exception as e:
        db.session.rollback()
        flash("Помилка під час зміни ролі.")

    return redirect(url_for('admin_users', user_id=id))


@app.route('/admin/users/delete/<int:id>')
def delete_user(id):
    if session.get('role') != 1:
        return redirect(url_for('login'))

    if id == 1:
        flash("Неможливо видалити головного адміністратора системи!")
        return redirect(url_for('admin_users'))

    try:
        db.session.execute(text("DELETE FROM user WHERE id_user = :id"), {"id": id})
        db.session.commit()
        flash("Користувача успішно видалено з системи!")
    except Exception as e:
        db.session.rollback()
        flash("Неможливо видалити користувача, у якого є активні замовлення.")

    return redirect(url_for('admin_users'))


@app.route('/admin/create_category', methods=['POST'])
def create_category():
    if session.get('role') != 1:
        return jsonify({'success': False, 'message': 'Access denied'})
    try:
        name = request.json.get('name')
        db.session.execute(text("INSERT INTO category (name) VALUES (:name)"), {"name": name})
        db.session.commit()
        return jsonify({'success': True})
    except:
        return jsonify({'success': False, 'message': 'Помилка створення'})


@app.route('/admin/create_subcategory', methods=['POST'])
def create_subcategory():
    if session.get('role') != 1:
        return jsonify({'success': False})
    try:
        name = request.json.get('name')
        cat_id = request.json.get('id_category')
        db.session.execute(text("INSERT INTO subcategory (name, id_category) VALUES (:name, :cat)"),
                           {"name": name, "cat": cat_id})
        db.session.commit()
        return jsonify({'success': True})
    except:
        return jsonify({'success': False})


@app.route('/admin/orders/update/<int:order_id>/<string:status>')
def update_order_status(order_id, status):
    if session.get('role') != 1:
        return redirect(url_for('login'))

    valid_statuses = ['Підтверджено', 'В обробці', 'Виконано']
    if status not in valid_statuses:
        status = 'В обробці'

    try:
        db.session.execute(
            text("UPDATE `order` SET status = :status WHERE id_order = :id"),
            {"status": status, "id": order_id}
        )
        db.session.commit()
        flash(f"Статус замовлення #{order_id} змінено на '{status}'", "success")
    except:
        db.session.rollback()
        flash("Не вдалося оновити статус", "danger")

    return redirect(url_for('admin_orders'))

@app.route('/api/reviews/<int:product_id>')
def get_reviews(product_id):
    try:
        reviews = db.session.execute(text("""
                                          SELECT r.id_review,
                                                 r.rating,
                                                 r.comment,
                                                 r.created_at,
                                                 r.admin_reply,
                                                 u.full_name as username
                                          FROM review r
                                                   LEFT JOIN user u ON r.id_user = u.id_user
                                          WHERE r.id_product = :pid
                                            AND (r.is_hidden = 0 OR r.is_hidden IS NULL)
                                          ORDER BY r.created_at DESC
                                          """), {"pid": product_id}).mappings().all()

        return jsonify([dict(review) for review in reviews])
    except Exception as e:
        print("Error loading reviews:", e)
        return jsonify([])


@app.route('/api/review', methods=['POST'])
def add_review():
    if 'user_id' not in session:
        return jsonify({"error": "Необхідно увійти"}), 401

    data = request.get_json()
    try:
        db.session.execute(text("""
                                INSERT INTO review (id_product, id_user, rating, comment)
                                VALUES (:product_id, :user_id, :rating, :comment)
                                """), {
                               "product_id": data['product_id'],
                               "user_id": session['user_id'],
                               "rating": int(data['rating']),
                               "comment": data['comment']
                           })
        db.session.commit()
        return jsonify({"success": True, "message": "Відгук додано"})
    except Exception as e:
        db.session.rollback()
        print("Error adding review:", e)
        return jsonify({"error": "Помилка при збереженні відгуку"}), 500


@app.route('/admin/reviews')
def admin_reviews():
    if session.get('role') != 1:
        flash("Доступ заборонено", "danger")
        return redirect(url_for('admin_main'))

    reviews_raw = db.session.execute(text("""
                                          SELECT r.*,
                                                 p.name      as product_name,
                                                 u.full_name as username
                                          FROM review r
                                                   JOIN product p ON r.id_product = p.id_product
                                                   LEFT JOIN user u ON r.id_user = u.id_user
                                          ORDER BY r.created_at DESC
                                          """)).mappings().all()

    reviews = [dict(r) for r in reviews_raw]

    return render_template('admin/reviews.html', reviews=reviews)


@app.route('/admin/delete_review/<int:review_id>', methods=['POST'])
def delete_review(review_id):
    if session.get('role') != 1:
        return jsonify({"success": False, "message": "Access denied"})

    try:
        db.session.execute(text("DELETE FROM review WHERE id_review = :id"), {"id": review_id})
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)})


@app.route('/admin/review/<int:review_id>/reply', methods=['POST'])
def admin_reply(review_id):
    if session.get('role') != 1: return jsonify({"success": False})
    data = request.get_json()
    db.session.execute(text("UPDATE review SET admin_reply = :reply WHERE id_review = :id"),
                       {"reply": data.get('admin_reply'), "id": review_id})
    db.session.commit()
    return jsonify({"success": True})


@app.route('/admin/review/<int:review_id>/hide', methods=['POST'])
def hide_review(review_id):
    if session.get('role') != 1: return jsonify({"success": False})
    data = request.get_json()
    db.session.execute(text("""
                            UPDATE review
                            SET is_hidden       = 1,
                                moderation_note = :note
                            WHERE id_review = :id
                            """), {"note": data.get('moderation_note'), "id": review_id})
    db.session.commit()
    return jsonify({"success": True})


@app.route('/admin/review/<int:review_id>/unhide', methods=['POST'])
def unhide_review(review_id):
    if session.get('role') != 1: return jsonify({"success": False})
    db.session.execute(text("UPDATE review SET is_hidden = 0 WHERE id_review = :id"),
                       {"id": review_id})
    db.session.commit()
    return jsonify({"success": True})


# Перегляд товарів у замовленні
@app.route('/admin/order/<int:order_id>/items')
def order_items(order_id):
    if session.get('role') != 1:
        return "<p class='text-danger'>Доступ заборонено</p>"

    order = db.session.execute(text("""
                                    SELECT *
                                    FROM `order`
                                    WHERE id_order = :id
                                    """), {"id": order_id}).mappings().first()

    items = db.session.execute(text("""
                                    SELECT oi.*, p.name, p.base_price
                                    FROM order_item oi
                                             JOIN product p ON oi.id_product = p.id_product
                                    WHERE oi.id_order = :oid
                                    ORDER BY p.name
                                    """), {"oid": order_id}).mappings().all()

    html = f"""
    <div class="alert alert-info mb-3">
        <strong>Замовлення #{order_id}</strong> — 
        Статус: <span class="badge bg-primary">{order.status if order and order.status else 'Підтверджено'}</span><br>
        Сума: <strong>{float(order.total_amount if order else 0):,.2f} грн</strong>
    </div>
    """

    if not items:
        html += """
        <div class="alert alert-warning">
            <h6>Товари не знайдено в order_item</h6>
            <p>Ймовірно, замовлення створювалося до оновлення логіки checkout.</p>
        </div>
        """
    else:
        html += f"<p class='text-success'><strong>Знайдено товарів: {len(items)}</strong></p>"

    if items:
        html += """
        <table class="table table-dark table-sm">
            <thead>
                <tr>
                    <th>Товар</th>
                    <th class="text-end">Кількість</th>
                    <th class="text-end">Ціна</th>
                    <th class="text-end">Сума</th>
                </tr>
            </thead>
            <tbody>
        """
        total = 0
        for item in items:
            qty = item.quantity
            price = float(item.price_at_time or 0)
            sum_item = qty * price
            total += sum_item
            html += f"""
                <tr>
                    <td>{item.name}</td>
                    <td class="text-end">{qty}</td>
                    <td class="text-end">{price:,.2f} грн</td>
                    <td class="text-end fw-bold">{sum_item:,.2f} грн</td>
                </tr>
            """
        html += f"""
            </tbody>
            <tfoot>
                <tr class="fw-bold">
                    <th colspan="3" class="text-end">Разом:</th>
                    <th class="text-end text-info">{total:,.2f} грн</th>
                </tr>
            </tfoot>
        </table>
        """

    return html

@app.route('/admin/orders/complete/<int:order_id>')
def complete_order(order_id):
    if session.get('role') != 1:
        return redirect(url_for('login'))

    try:
        # Отримуємо товари замовлення
        items = db.session.execute(text("""
            SELECT id_product, quantity 
            FROM order_item 
            WHERE id_order = :oid
        """), {"oid": order_id}).mappings().all()

        for item in items:
            db.session.execute(text("""
                UPDATE product 
                SET stock = GREATEST(0, stock - :qty) 
                WHERE id_product = :pid
            """), {"pid": item.id_product, "qty": item.quantity})

        db.session.execute(text("""
            UPDATE `order` 
            SET status = 'Виконано' 
            WHERE id_order = :id
        """), {"id": order_id})

        db.session.commit()
        flash(f"Замовлення #{order_id} виконано. Залишки оновлено.", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Помилка: {str(e)}", "danger")

    return redirect(url_for('admin_orders'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)