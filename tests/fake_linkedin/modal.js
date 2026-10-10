// LinkedIn-like Easy Apply: a modal (role=dialog) on the offer page, 3 steps, URL unchanged
function openModal() {
  const d = document.createElement('div');
  d.setAttribute('role', 'dialog'); d.className = 'artdeco-modal';
  d.style = 'position:fixed;top:40px;left:40px;width:600px;background:#fff;border:2px solid #000;padding:12px';
  document.body.appendChild(d);
  step1(d);
}
function step1(d) {
  d.innerHTML = `<h2>Postuler chez ACME</h2>
    <label for="xp">Combien d'années d'expérience avez-vous en Python ?</label><input id="xp" required>
    <label for="en">Niveau d'anglais</label><select id="en"><option></option><option>Courant</option><option>Notions</option></select>
    <button aria-label="Ignorer">X</button> <button id="next">Suivant</button>`;
  d.querySelector('#next').onclick = () => step2(d);
}
function step2(d) {
  d.innerHTML = `<h2>Vérifier votre candidature</h2>
    <input type="checkbox" id="follow" checked><label for="follow">Suivre ACME pour rester informé de son actualité</label>
    <button>Enregistrer</button> <button id="review">Vérifier</button>`;
  d.querySelector('#review').onclick = () => step3(d);
}
function step3(d) {
  const followed = d.querySelector('#follow').checked;
  d.innerHTML = `<h2>Dernière étape</h2><p>follow=${followed}</p><button id="send">Envoyer la candidature</button>`;
  d.querySelector('#send').onclick = () => { d.innerHTML = `<h2>Candidature envoyée</h2><p>follow=${followed}</p>`; };
}
