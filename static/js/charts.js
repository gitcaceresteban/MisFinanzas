/**
 * Helpers para gráficos con Chart.js
 */

const isDark = () => document.documentElement.classList.contains('dark');
const textColor = () => isDark() ? '#cbd5e1' : '#475569';
const gridColor = () => isDark() ? 'rgba(148, 163, 184, 0.1)' : 'rgba(148, 163, 184, 0.2)';

window.chartDefaults = {
    color: textColor(),
    plugins: {
        legend: {
            labels: { color: textColor(), font: { size: 11, family: 'system-ui, sans-serif' } }
        },
        tooltip: {
            backgroundColor: isDark() ? '#0f172a' : '#fff',
            titleColor: isDark() ? '#fff' : '#0f172a',
            bodyColor: isDark() ? '#cbd5e1' : '#475569',
            borderColor: isDark() ? '#1e293b' : '#e2e8f0',
            borderWidth: 1,
            padding: 12,
            cornerRadius: 8,
            callbacks: {
                label: (ctx) => {
                    const v = ctx.parsed.y ?? ctx.parsed;
                    return ' ' + window.fmtCLP(v);
                }
            }
        }
    }
};

/**
 * Crea gráfico de doughnut de gastos por categoría.
 */
window.makeCategoryChart = function(canvasId, data) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;

    return new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: data.map(d => d.name),
            datasets: [{
                data: data.map(d => d.total),
                backgroundColor: data.map(d => d.color || '#64748b'),
                borderColor: isDark() ? '#0f172a' : '#fff',
                borderWidth: 2,
            }]
        },
        options: {
            ...window.chartDefaults,
            cutout: '65%',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                ...window.chartDefaults.plugins,
                legend: { position: 'right', labels: { color: textColor() } }
            }
        }
    });
};

/**
 * Crea gráfico de línea de evolución mensual.
 */
window.makeEvolutionChart = function(canvasId, data) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;

    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.map(d => d.month),
            datasets: [
                {
                    label: 'Gastos',
                    data: data.map(d => d.expenses || 0),
                    borderColor: '#f43f5e',
                    backgroundColor: 'rgba(244, 63, 94, 0.1)',
                    fill: true,
                    tension: 0.3,
                },
                {
                    label: 'Ingresos',
                    data: data.map(d => d.incomes || 0),
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    fill: true,
                    tension: 0.3,
                }
            ]
        },
        options: {
            ...window.chartDefaults,
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { ticks: { color: textColor() }, grid: { color: gridColor() } },
                y: {
                    ticks: {
                        color: textColor(),
                        callback: (v) => window.fmtCLP(v)
                    },
                    grid: { color: gridColor() }
                }
            }
        }
    });
};

/**
 * Crea gráfico de flujo de caja proyectado.
 */
window.makeCashflowChart = function(canvasId, data) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;

    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.map(d => d.date),
            datasets: [{
                label: 'Saldo proyectado',
                data: data.map(d => d.balance),
                borderColor: '#6366f1',
                backgroundColor: 'rgba(99, 102, 241, 0.1)',
                fill: true,
                tension: 0.1,
                pointRadius: 0,
                pointHoverRadius: 6,
            }]
        },
        options: {
            ...window.chartDefaults,
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            scales: {
                x: { ticks: { color: textColor(), maxTicksLimit: 10 }, grid: { display: false } },
                y: {
                    ticks: {
                        color: textColor(),
                        callback: (v) => window.fmtCLP(v)
                    },
                    grid: { color: gridColor() }
                }
            }
        }
    });
};
