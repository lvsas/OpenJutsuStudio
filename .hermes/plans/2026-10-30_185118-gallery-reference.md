# A character from the gallery, as a swap reference

**Branche** : `feat/gallery-reference` · **Statut** : plan, aucun code produit encore.

## Objectif

Choisir une référence de swap **dans la galerie de personnages**, sans passer par
l'explorateur de fichiers du PC. Un personnage déjà généré et sauvegardé doit être
utilisable tel quel dans H3, LTX et la timeline.

## Principe

On ne crée **aucun nouveau chemin de confiance**. Un personnage sauvegardé est déjà
prouvé intact : `CharacterLibrary._completed()` vérifie la capsule, la taille, le
SHA-256 de l'image et du caption, et la validité du PNG. On réutilise exactement
cette vérification, puis on **copie** l'image dans les emplacements de référence du
job, comme un upload. En aval, rien ne change.

## Étapes

### 1. Résolveur, testé seul (TDD)

`src/character_references.py`

```python
def resolve(ids, library, limit):
    """Return (paths, reasons). Never raises for one bad id."""
```

- dédoublonne en gardant l'ordre ;
- refuse au-delà de `limit` ;
- pour chaque id : `library.completed_path(id)` → chemin contenu, ou une raison lisible ;
- renvoie des **raisons** par id refusé, jamais une exception globale.

Test `tests/test_character_references.py`, rouge d'abord :
id inconnu → raison « job inconnu » ; id non-personnage → « pas un personnage » ;
image modifiée → « image altérée » ; deux fois le même id → une seule référence.

### 2. H3 accepte les deux sources

`src/h3_api.py`, après `form = await request.form()` :

```python
gallery_ids = [str(item) for item in form.getlist('reference_job_ids')]
paths, reasons = character_references.resolve(gallery_ids, self.library, REFERENCE_SLOTS - len(reference_images))
if reasons:
    raise HTTPException(422, '; '.join(reasons))
total = len(reference_images) + len(paths)
if not 1 <= total <= REFERENCE_SLOTS:
    raise HTTPException(422, f'H3 accepts between 1 and {REFERENCE_SLOTS} reference images')
```

Les `paths` sont copiés dans `media_dir / f'{job_id}-reference-{n}.png'` avec
`shutil.copyfile`, exactement comme un upload. Le reste du pipeline est inchangé.

Test : un job factice sauvegardé en bibliothèque, un POST sans fichier mais avec
`reference_job_ids`, réponse 202 et le job porte bien le nombre d'images attendu.

### 3. Interface : un onglet, pas un formulaire de plus

Dans `index.html` (LTX) et `h3.html` : à côté de « From this PC », un bouton
**Gallery** qui ouvre les vignettes de `/api/characters/library`. Un clic pose un
`<input type="hidden" name="reference_job_ids" value="…">`. Les deux sources
coexistent, l'ordre est celui de sélection, le compteur reste celui d'aujourd'hui.

Test de contrat `.mjs` : sélectionner deux vignettes produit deux champs cachés
ordonnés ; en retirer une retire son champ ; le compteur affiché suit.

### 4. Dégradation honnête

- Galerie vide → l'onglet affiche « Aucun personnage sauvegardé » et un lien vers
  `/characters`, jamais un onglet vide.
- Personnage supprimé entre l'affichage et l'envoi → message nommant le personnage,
  pas un 500.

## Ce qu'on ne fait pas

- Pas de base de données.
- Pas de nouveau stockage : l'image reste dans `work/media`.
- Pas de changement du contrat d'upload existant (les clients actuels continuent).
- Pas de modification de la timeline dans cette branche.

## Sortie

- PR en brouillon, CI verte sur la branche.
- Test manuel : un personnage de la galerie dans un swap H3, puis LTX.
- Fusion seulement après ce test manuel.
