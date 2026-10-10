// LinkedIn-like Easy Apply in 4 steps (modal): contact -> CV -> questions -> review/send. Validates required fields.
window.sent = 0;
function openEasy() {
  const d = document.createElement('div');
  d.setAttribute('role', 'dialog');
  d.style = 'position:fixed;top:20px;left:20px;width:680px;background:#fff;border:2px solid #000;padding:10px';
  document.body.appendChild(d);
  const steps = [
    `<h3>Coordonnées</h3>
     <label for="em">Adresse e-mail*</label><select id="em" required><option>Sélectionnez une option</option><option>adil@example.com</option></select>
     <label for="cc">Code pays</label><select id="cc"><option>France (+33)</option></select>
     <label for="ph">Numéro de téléphone mobile*</label><input id="ph" required>`,
    `<h3>CV</h3><input type="radio" name="cv" id="cv1" checked><label for="cv1">Cv_Adil_AMZAZ2_en.pdf</label>`,
    `<h3>Questions supplémentaires</h3>
     <label for="py">Combien d'années d'expérience avez-vous avec Python ?*</label><input id="py" type="number" required>
     <fieldset><legend>Êtes-vous à l'aise avec le travail hybride ?*</legend>
       <input type="radio" name="hy" id="hy1"><label for="hy1">Oui</label>
       <input type="radio" name="hy" id="hy2"><label for="hy2">Non</label></fieldset>`,
    `<h3>Vérifier votre candidature</h3>
     <input type="checkbox" id="fo" checked><label for="fo">Suivre ${document.title.split(' | ')[1]} pour rester informé</label>`,
  ];
  let i = 0;
  const render = () => {
    d.innerHTML = `<h2>Postuler</h2>${steps[i]}<div id="err"></div>` +
      (i < 3 ? `<button id="nx">${i === 2 ? 'Vérifier' : 'Suivant'}</button>` : `<button id="send">Envoyer la candidature</button>`);
    if (i < 3) d.querySelector('#nx').onclick = () => {
      const bad = [...d.querySelectorAll('[required]')].some(e => !e.value || e.selectedIndex === 0)
                  || (i === 2 && !d.querySelector('input[name=hy]:checked'));
      if (bad) { d.querySelector('#err').innerHTML = '<p role="alert">Veuillez remplir ce champ obligatoire</p>'; return; }
      i++; render();
    };
    else d.querySelector('#send').onclick = () => { window.sent++; window.follow = d.querySelector('#fo').checked;
                                                    d.innerHTML = '<h2>Candidature envoyée</h2>'; };
  };
  d.addEventListener('change', () => { const e = d.querySelector('#err'); if (e) e.innerHTML = ''; });   // fixed -> error gone
  render();
}
