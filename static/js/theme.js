/**
 * Manejo de tema claro/oscuro
 * Soporta: light, dark, auto
 */

function setTheme(mode) {
    localStorage.setItem('theme', mode);
    applyTheme();
}

function applyTheme() {
    const t = localStorage.getItem('theme') || 'auto';
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (t === 'dark' || (t === 'auto' && prefersDark)) {
        document.documentElement.classList.add('dark');
    } else {
        document.documentElement.classList.remove('dark');
    }
}

// Escuchar cambios en preferencia del sistema
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if ((localStorage.getItem('theme') || 'auto') === 'auto') {
        applyTheme();
    }
});

// Aplicar al cargar
applyTheme();
