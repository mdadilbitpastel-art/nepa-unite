(function(){
  var el = document.getElementById('admin-chart-data');
  if (!el) return;
  var d = JSON.parse(el.textContent);
  var charts = [];

  var colors = {
    indigo:  '#6366f1',
    amber:   '#f59e0b',
    emerald: '#10b981',
    rose:    '#f43f5e',
    cyan:    '#06b6d4',
    violet:  '#8b5cf6',
    pink:    '#ec4899'
  };

  function getThemeColors() {
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    return {
      text: isDark ? '#f1f5f9' : '#0f172a',
      grid: isDark ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.08)',
      ordersFill: isDark ? 'rgba(99,102,241,.12)' : 'rgba(99,102,241,.08)'
    };
  }

  function render() {
    charts.forEach(function(c){ c.destroy(); });
    charts = [];
    var t = getThemeColors();

    Chart.defaults.font = { family: '-apple-system,BlinkMacSystemFont,Inter,sans-serif', size: 11 };
    Chart.defaults.color = t.text;
    Chart.defaults.plugins.legend.display = false;

    charts.push(new Chart(document.getElementById('adminRevenueChart'), {
      type: 'bar',
      data: { labels: d.revenueLabels, datasets: [{ data: d.revenueData, backgroundColor: colors.emerald, borderRadius: 4, barPercentage: 0.6 }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, grid: { color: t.grid }, ticks: { callback: function(v){ return '$' + v; } } }, x: { grid: { display: false } } }, plugins: { tooltip: { callbacks: { label: function(c){ return '$' + c.parsed.y.toFixed(2); } } } } }
    }));

    charts.push(new Chart(document.getElementById('adminOrdersChart'), {
      type: 'line',
      data: { labels: d.revenueLabels, datasets: [{ data: d.ordersData, borderColor: colors.indigo, backgroundColor: t.ordersFill, fill: true, tension: 0.3, pointRadius: 4, pointBackgroundColor: colors.indigo }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, grid: { color: t.grid }, ticks: { stepSize: 1 } }, x: { grid: { display: false } } }, plugins: { tooltip: { callbacks: { label: function(c){ return c.parsed.y + ' orders'; } } } } }
    }));

    // Match the order-status badge colors used across the app (see base.html
    // .pill.<status>). Mapped by label so each slice keeps its own color
    // regardless of which statuses are present.
    var orderStatusPalette = {
      draft: '#64748b', confirmed: '#2563eb', fulfillment: '#ca8a04',
      shipped: '#7c3aed', delivered: '#16a34a', closed: '#0d9488', cancelled: '#991b1b'
    };
    var statusColors = (d.orderStatusLabels || []).map(function (lbl) {
      return orderStatusPalette[String(lbl).toLowerCase()] || colors.indigo;
    });
    charts.push(new Chart(document.getElementById('adminOrderStatusChart'), {
      type: 'doughnut',
      data: { labels: d.orderStatusLabels, datasets: [{ data: d.orderStatusData, backgroundColor: statusColors, borderWidth: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: '60%', plugins: { legend: { display: true, position: 'bottom', labels: { padding: 12, usePointStyle: true, pointStyle: 'circle', color: t.text } } } }
    }));

    var roleColors = [colors.rose, colors.cyan, colors.amber, colors.violet];
    charts.push(new Chart(document.getElementById('adminRoleChart'), {
      type: 'doughnut',
      data: { labels: d.roleLabels, datasets: [{ data: d.roleData, backgroundColor: roleColors.slice(0, d.roleLabels.length), borderWidth: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: '60%', plugins: { legend: { display: true, position: 'bottom', labels: { padding: 12, usePointStyle: true, pointStyle: 'circle', color: t.text } } } }
    }));
  }

  render();
  document.addEventListener('themeChanged', render);
})();
