// Free-Work-like: "Postuler" draws the application form IN the offer page (logged-in account)
function showForm() {
  const f = document.createElement('form');
  f.onsubmit = e => e.preventDefault();
  f.innerHTML = `<h2>Postuler à cette offre</h2>
    <label for="m">Message au recruteur</label><textarea id="m"></textarea>
    <label for="cv">CV (PDF)</label><input id="cv" type="file" required>
    <input type="checkbox" id="p"><label for="p">J'accepte les conditions générales d'utilisation</label>
    <button id="s">Envoyer ma candidature</button>`;
  document.getElementById('form').appendChild(f);
  f.querySelector('#s').onclick = () => { if (f.querySelector('#cv').files.length) f.innerHTML = '<h2>Candidature envoyée</h2>'; };
}
