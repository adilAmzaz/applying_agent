// HelloWork-like: the application form is drawn IN the offer page (no dialog, same URL)
function showForm() {
  const f = document.createElement('form');
  f.onsubmit = e => e.preventDefault();
  f.innerHTML = `<h2>Postuler à cette offre</h2>
    <label for="n">Nom complet</label><input id="n" required>
    <label for="e">Email</label><input id="e" type="email" required>
    <label for="cv">CV (PDF)</label><input id="cv" type="file" required>
    <input type="checkbox" id="p"><label for="p">J'ai lu et j'accepte la politique de confidentialité</label>
    <input type="checkbox" id="a" checked><label for="a">Recevoir des alertes et offres similaires</label>
    <button id="s">Envoyer ma candidature</button>`;
  document.getElementById('form').appendChild(f);
  f.querySelector('#s').onclick = () => { f.innerHTML = '<h2>Candidature envoyée</h2>'; };
}
