// WTTJ-like apply form in a modal (role=dialog), URL unchanged
function openModal() {
  const d = document.createElement('div');
  d.setAttribute('role', 'dialog');
  d.style = 'position:fixed;top:30px;left:30px;width:640px;background:#fff;border:2px solid #000;padding:12px';
  d.innerHTML = `<h2>Postuler</h2>
    <label for="n">Nom complet</label><input id="n" required>
    <label for="e">Email</label><input id="e" type="email" required>
    <label for="cv">CV (PDF)</label><input id="cv" type="file" required>
    <input type="checkbox" id="p"><label for="p">J'accepte la politique de confidentialité</label>
    <input type="checkbox" id="a" checked><label for="a">Recevoir des alertes emploi et la newsletter</label>
    <button id="s">Envoyer ma candidature</button>`;
  document.body.appendChild(d);
  d.querySelector('#s').onclick = () => { d.innerHTML = `<h2>Candidature envoyée</h2><p>alerts=${d.querySelector('#a').checked}</p>`; };
}
