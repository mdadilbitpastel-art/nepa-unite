(function(){
  var el = document.getElementById('chart-data');
  if (!el) return;
  var d = JSON.parse(el.textContent);
  var charts = [];

  function getThemeColors() {
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    return {
      primary:    isDark ? '#60a5fa' : '#0c2340',
      accent:     isDark ? '#e0ad5a' : '#d4a155',
      success:    isDark ? '#34d399' : '#047857',
      warning:    isDark ? '#fbbf24' : '#b45309',
      danger:     isDark ? '#f87171' : '#dc2626',
      muted:      '#94a3b8',
      text:       isDark ? '#f1f5f9' : '#0f172a',
      grid:       isDark ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.08)',
      primaryFill: isDark ? 'rgba(96,165,250,.1)' : 'rgba(12,35,64,.08)'
    };
  }

  function render() {
    charts.forEach(function(c){ c.destroy(); });
    charts = [];
    var c = getThemeColors();

    Chart.defaults.font = { family: '-apple-system,BlinkMacSystemFont,Inter,sans-serif', size: 11 };
    Chart.defaults.color = c.text;
    Chart.defaults.plugins.legend.display = false;

    charts.push(new Chart(document.getElementById('revenueChart'), {
      type: 'bar',
      data: { labels: d.revenueLabels, datasets: [{ data: d.revenueData, backgroundColor: c.accent, borderRadius: 4, barPercentage: 0.6 }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, grid: { color: c.grid }, ticks: { callback: function(v){ return '$' + v; } } }, x: { grid: { display: false } } }, plugins: { tooltip: { callbacks: { label: function(ctx){ return '$' + ctx.parsed.y.toFixed(2); } } } } }
    }));

    charts.push(new Chart(document.getElementById('ordersChart'), {
      type: 'line',
      data: { labels: d.revenueLabels, datasets: [{ data: d.ordersData, borderColor: c.primary, backgroundColor: c.primaryFill, fill: true, tension: 0.3, pointRadius: 4, pointBackgroundColor: c.primary }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, grid: { color: c.grid }, ticks: { stepSize: 1 } }, x: { grid: { display: false } } }, plugins: { tooltip: { callbacks: { label: function(ctx){ return ctx.parsed.y + ' orders'; } } } } }
    }));

    // Match the order-status badge colors (see base.html .pill.<status>),
    // mapped by label so each slice keeps its own colour.
    var orderStatusPalette = {
      draft: '#64748b', confirmed: '#2563eb', fulfillment: '#ca8a04',
      shipped: '#7c3aed', delivered: '#16a34a', closed: '#0d9488', cancelled: '#991b1b'
    };
    var statusColors = (d.orderStatusLabels || []).map(function (lbl) {
      return orderStatusPalette[String(lbl).toLowerCase()] || c.primary;
    });
    charts.push(new Chart(document.getElementById('orderStatusChart'), {
      type: 'doughnut',
      data: { labels: d.orderStatusLabels, datasets: [{ data: d.orderStatusData, backgroundColor: statusColors, borderWidth: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: '60%', plugins: { legend: { display: true, position: 'bottom', labels: { padding: 12, usePointStyle: true, pointStyle: 'circle' } } } }
    }));

    charts.push(new Chart(document.getElementById('productStatusChart'), {
      type: 'doughnut',
      data: { labels: ['Active', 'Inactive', 'Low stock'], datasets: [{ data: [d.activeProducts, d.inactiveProducts, d.lowStock], backgroundColor: [c.success, c.muted, c.danger], borderWidth: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: '60%', plugins: { legend: { display: true, position: 'bottom', labels: { padding: 12, usePointStyle: true, pointStyle: 'circle' } } } }
    }));
  }

  render();
  document.addEventListener('themeChanged', render);
})();
