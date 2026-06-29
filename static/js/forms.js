/**
 * Helpers de formularios.
 *  - Autoformato de montos en CLP mientras se escribe (1.234.567).
 *  - Confirmación de acciones destructivas.
 *
 * Los inputs de dinero usan class="money-input" (o [data-money]) y son
 * type="text" inputmode="numeric". El backend (parse_money) entiende el valor
 * con puntos, así que no hace falta limpiarlos al enviar.
 */

// Inserta separador de miles con punto en un string de solo dígitos.
function _groupThousands(digits) {
    return digits.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

// Formatea el valor "en vivo" preservando la posición del cursor.
function _liveFormatMoney(el) {
    const negative = el.value.trim().startsWith('-');

    // Cuántos dígitos hay a la izquierda del cursor (para restaurarlo luego).
    const caret = el.selectionStart || 0;
    const digitsLeft = el.value.slice(0, caret).replace(/\D/g, '').length;

    let digits = el.value.replace(/\D/g, '').replace(/^0+(?=\d)/, '');
    let formatted = digits ? _groupThousands(digits) : '';
    if (negative && formatted) formatted = '-' + formatted;

    el.value = formatted;

    // Reposicionar el cursor después de la misma cantidad de dígitos.
    let pos = 0, seen = 0;
    while (pos < el.value.length && seen < digitsLeft) {
        if (/\d/.test(el.value[pos])) seen++;
        pos++;
    }
    try { el.setSelectionRange(pos, pos); } catch (e) {}
}

// Formatea el valor inicial que llega del servidor (ej. "506915.0").
function _formatInitialMoney(el) {
    if (el.value === null || el.value === undefined || el.value.trim() === '') return;
    const n = Math.round(parseFloat(el.value));
    if (isNaN(n)) { el.value = ''; return; }
    const sign = n < 0 ? '-' : '';
    el.value = sign + _groupThousands(Math.abs(n).toString());
}

function _moneyInputs(root) {
    return (root || document).querySelectorAll('.money-input, [data-money]');
}

document.addEventListener('DOMContentLoaded', () => {
    _moneyInputs().forEach(_formatInitialMoney);
});

document.addEventListener('input', (e) => {
    if (e.target && e.target.matches && e.target.matches('.money-input, [data-money]')) {
        _liveFormatMoney(e.target);
        // Notificar a otros (ej. simuladores) que el valor cambió.
        e.target.dispatchEvent(new CustomEvent('money:changed', { bubbles: true }));
    }
});

// Confirmar acciones destructivas (formularios con data-confirm).
document.addEventListener('submit', (e) => {
    const confirmText = e.target.dataset ? e.target.dataset.confirm : null;
    if (confirmText && !confirm(confirmText)) {
        e.preventDefault();
    }
}, true);

// Helper global: convierte "1.234.567" -> 1234567 (número).
window.parseMoney = function (str) {
    if (str === null || str === undefined) return 0;
    const neg = String(str).trim().startsWith('-');
    const digits = String(str).replace(/\D/g, '');
    const n = digits ? parseInt(digits, 10) : 0;
    return neg ? -n : n;
};

// Helper global para formatear cifras en cualquier elemento con data-clp-display.
function refreshClpDisplays() {
    document.querySelectorAll('[data-clp-display]').forEach(el => {
        const raw = parseFloat(el.dataset.clpDisplay);
        if (!isNaN(raw)) {
            el.textContent = '$' + Math.round(raw).toLocaleString('es-CL').replace(/,/g, '.');
        }
    });
}
document.addEventListener('DOMContentLoaded', refreshClpDisplays);
