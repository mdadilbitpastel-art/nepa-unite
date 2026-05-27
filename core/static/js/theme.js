(function(){
  var t = localStorage.getItem('theme') ||
          (matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', t);
})();

function toggleTheme(){
  document.documentElement.classList.add('theme-transition');
  var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
  var mc = document.querySelector('meta[name="theme-color"]');
  if (mc) mc.setAttribute('content', next === 'dark' ? '#0b1222' : '#0c2340');
  setTimeout(function(){ document.documentElement.classList.remove('theme-transition'); }, 350);
  document.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme: next } }));
}

document.addEventListener('DOMContentLoaded', function(){
  var btns = document.querySelectorAll('[data-theme-toggle]');
  for (var i = 0; i < btns.length; i++) {
    btns[i].addEventListener('click', toggleTheme);
  }
});
