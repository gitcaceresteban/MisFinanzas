/**
 * Interacciones generales de la app.
 */

// Mostrar/ocultar elementos por data-toggle
document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-toggle]');
    if (btn) {
        const target = document.querySelector(btn.dataset.toggle);
        if (target) {
            target.classList.toggle('hidden');
        }
    }
});

// Auto-cerrar modales con backdrop
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-backdrop')) {
        const modal = e.target.closest('[x-data]');
        if (modal && modal.__x) {
            // Alpine se encarga
        }
    }
});

// Helper global para formatear CLP
window.fmtCLP = function(n) {
    if (n === null || n === undefined || isNaN(n)) return '$0';
    const rounded = Math.round(n);
    const sign = rounded < 0 ? '-' : '';
    return sign + '$' + Math.abs(rounded).toLocaleString('es-CL').replace(/,/g, '.');
};

// Listener: re-renderizar iconos Lucide cuando Alpine actualice DOM
document.addEventListener('alpine:init', () => {
    setTimeout(() => {
        if (window.lucide) lucide.createIcons();
    }, 100);
});
