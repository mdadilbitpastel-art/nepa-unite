(function(){
  var key = '_scroll_' + location.pathname + location.search;
  var raw = sessionStorage.getItem(key);
  if (raw) {
    var data = JSON.parse(raw);
    if (Date.now() - data.t < 5000) { window.scrollTo(0, data.y); }
    sessionStorage.removeItem(key);
  }
  window.addEventListener('beforeunload', function(){
    sessionStorage.setItem(key, JSON.stringify({ y: window.scrollY, t: Date.now() }));
  });
})();
