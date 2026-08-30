# Studio headless et projets portables

Le mode headless transforme une recette JSON versionnée en un vrai projet Studio. Il
utilise exactement le même modèle, les mêmes transitions et le même pipeline de rendu
que l’interface desktop. Aucun backend ni service distant n’est impliqué.

## Commande

```powershell
artanimate studio build .\transition.json --output .\mon-projet
```

L’exécutable autonome expose le même contrat :

```powershell
.\ArtAnimate.exe --headless-studio .\transition.json .\mon-projet .\rapport.json
```

Une construction réussie produit :

```text
mon-projet/
  project.artanimate       projet éditable et réouvrable dans le Studio
  recipe.json              recette canonique, avec chemins portables
  assets/
    artwork/               copie locale de l’œuvre
    media/                 copies locales des photos, vidéos et sons
  snapshots/               versions précédentes, créées seulement si le projet change
  headless-report.json     rapport structuré de la commande CLI
```

Les sorties demandées dans `outputs` sont créées dans le même dossier. Les chemins
absolus présents dans la recette source ne sont jamais conservés dans le projet final.

## Recette minimale

```json
{
  "schema_version": 1,
  "name": "Œuvre vers réel",
  "artwork": "./artwork.jpg",
  "project": {
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "quality": "fast",
    "crf": 18,
    "audio_mode": "reference"
  },
  "media": {
    "mur3": {"path": "./mur3.jpg", "kind": "image"},
    "mur2": {"path": "./mur2.jpg", "kind": "image"}
  },
  "shots": [
    {
      "id": "virtual",
      "kind": "artwork_3d",
      "duration_frames": 240,
      "settings": {
        "render_config": {"effect": "sand", "seed": 31},
        "camera": {"motion": "top_drift", "motion_strength": 0.55}
      }
    },
    {
      "id": "mur3",
      "kind": "still",
      "asset": "mur3",
      "duration_frames": 90,
      "camera": {
        "keyframes": [
          {"frame": 0, "x": 0.49, "y": 0.5, "zoom": 1.0},
          {"frame": 89, "x": 0.51, "y": 0.49, "zoom": 1.08,
           "easing": "ease_in_out"}
        ]
      }
    },
    {
      "id": "mur2",
      "kind": "still",
      "asset": "mur2",
      "duration_frames": 120,
      "camera": {
        "keyframes": [
          {"frame": 0, "x": 0.52, "y": 0.5, "zoom": 1.08},
          {"frame": 119, "x": 0.5, "y": 0.5, "zoom": 1.0,
           "easing": "ease_out"}
        ]
      }
    }
  ],
  "transitions": [
    {
      "kind": "cut",
      "from": "virtual",
      "to": "mur3",
      "duration_frames": 1
    },
    {
      "kind": "cut",
      "from": "mur3",
      "to": "mur2",
      "duration_frames": 1
    }
  ],
  "outputs": {
    "control_sheet": "renders/controls.jpg",
    "export": "renders/transition.mp4",
    "control_width": 270
  }
}
```

Les médias sont résolus relativement au fichier de recette. Les identifiants acceptent
les lettres ASCII, chiffres, points, tirets et underscores.

## Plans et transitions

Types de plan visuel :

- `artwork_2d` et `artwork_3d` utilisent l’œuvre centrale ;
- `still` référence un média `image` ;
- `video` référence un média `video` et accepte `source_in_frame` ;
- la section `audio` référence les médias `audio`.

Transitions :

- `cut` relie deux plans consécutifs sans recouvrement ;
- `dissolve` crée un fondu temporel ;
- `manual_match` raccorde un plan de l’œuvre à une photo ou une vidéo réelle et
  conserve tous ses réglages éditables dans le projet.

Le nombre total de frames est la somme des durées des plans. Une transition visuelle
utilise des poignées autour de sa coupe sans modifier cette durée ; une coupe franche
passe directement au plan suivant. L’exemple de référence dure 15 secondes à 30 FPS.

## Reconstruction et sauvegardes

La compilation est déterministe : recette et médias identiques donnent le même projet,
le même identifiant et aucun snapshot supplémentaire. Lorsqu’un changement réel est
détecté, l’ancienne version complète est archivée dans `snapshots/0001-<digest>.zip`
avant le remplacement atomique du projet courant.

Une recette invalide, un média absent ou un rendu en échec laisse le dernier projet
valide intact. Le rapport JSON est tout de même écrit avec `success: false`, le type
d’erreur et son message.

## Contrôle et export

`control_sheet` génère automatiquement des images représentatives des plans et des
transitions, avec leur numéro de frame et leur timecode. `export` encode le film complet
avec les réglages du projet. Les deux sorties passent par le pipeline canonique du
Studio ; elles ne sont donc pas des aperçus alternatifs.

Les options CLI `--controls` et `--export` peuvent remplacer ponctuellement les sorties
de la recette. Le projet portable reste alors identique.
