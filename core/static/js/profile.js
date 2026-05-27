/* Profile page — logo preview + change-password modal */
(function(){
  /* ── Logo preview ── */
  var logoInput = document.getElementById('id_logo');
  var logoLabel = document.querySelector('.pf-logo-label');
  if (logoInput && logoLabel) {
    logoInput.addEventListener('change', function(){
      var file = this.files && this.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function(e){
        var svg = logoLabel.querySelector('.pf-logo-default');
        if (svg) svg.style.display = 'none';
        var img = logoLabel.querySelector('.pf-logo-preview');
        if (!img) {
          img = document.createElement('img');
          img.className = 'pf-logo-preview';
          img.alt = '';
          logoLabel.insertBefore(img, logoLabel.firstChild);
        }
        img.src = e.target.result;
      };
      reader.readAsDataURL(file);
    });
  }
})();
