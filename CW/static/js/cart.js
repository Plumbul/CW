// Функція додавання товару в кошик
function addToCart(productId, productName, price) {
    let cart = JSON.parse(localStorage.getItem('cart')) || [];

    const existingItem = cart.find(item => item.id === productId);
    if (existingItem) {
        existingItem.quantity += 1;
    } else {
        cart.push({
            id: productId,
            name: productName,
            price: parseFloat(price),
            quantity: 1
        });
    }

    localStorage.setItem('cart', JSON.stringify(cart));
    updateBadges();
    alert(`Товар "${productName}" додано до кошика!`);
}

// Функція для Обраного
function toggleFavorite(productId, productName, price) {
    let favorites = JSON.parse(localStorage.getItem('favorites')) || [];
    const index = favorites.findIndex(item => item.id === productId);

    if (index > -1) {
        favorites.splice(index, 1);
        alert("Видалено з обраного");
    } else {
        favorites.push({ id: productId, name: productName, price: price });
        alert("Додано в обране!");
    }

    localStorage.setItem('favorites', JSON.stringify(favorites));
    updateBadges();
}

// Оновлення лічильників у хедері
function updateBadges() {
    // Кошик
    let cart = JSON.parse(localStorage.getItem('cart')) || [];
    const cartTotal = cart.reduce((sum, item) => sum + item.quantity, 0);
    const cartBadge = document.getElementById('cart-count');
    if (cartBadge) cartBadge.innerText = cartTotal;

    // Обране
    let favorites = JSON.parse(localStorage.getItem('favorites')) || [];
    const favBadge = document.getElementById('fav-count');
    if (favBadge) {
        favBadge.innerText = favorites.length;
        favBadge.style.display = favorites.length > 0 ? 'inline' : 'none';
    }
}

document.addEventListener('DOMContentLoaded', updateBadges);