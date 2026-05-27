/* Signup page — logo preview */
(function(){
  var input = document.getElementById('id_logo');
  if (!input) return;
  input.addEventListener('change', function(){
    var file = this.files && this.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function(e){
      var preview = document.getElementById('signupLogoPreview');
      var img = document.getElementById('signupLogoImg');
      var placeholder = document.getElementById('signupLogoPlaceholder');
      if (img) img.src = e.target.result;
      if (preview) preview.style.display = '';
      if (placeholder) placeholder.style.display = 'none';
    };
    reader.readAsDataURL(file);
  });
})();
