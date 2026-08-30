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
    source/                photo source intacte si une préparation est demandée
    artwork/               œuvre prête pour les plans 2D/3D
      *.rectification.json contour, confiance et résolution du redressement
    media/                 copies locales des photos, vidéos et sons
    semantic/              masques canoniques des régions animables
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
  "artwork_preparation": {
    "mode": "auto_rectify",
    "minimum_confidence": 0.75,
    "inset_ratio": 0.003,
    "max_output_edge": 2048
  },
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

## Préparation non destructive de l’œuvre

`artwork_preparation.mode: "auto_rectify"` détecte les quatre arêtes franches de la
toile, calcule une homographie et utilise l’image redressée dans tous les plans
`artwork_2d` et `artwork_3d`. La photo originale est conservée dans `assets/source`.
Le dossier `assets/artwork` contient l’image dérivée, un manifeste JSON avec les
quatre coins, la confiance et la résolution, ainsi qu’un aperçu de détection.

La compilation s’arrête sans remplacer le projet courant si la confiance est sous
`minimum_confidence`. Le mode par défaut `none` conserve le comportement historique.

## Plans et transitions

Types de plan visuel :

- `prologue` produit une scène typographique locale sans afficher l’œuvre ;
- `artwork_2d` et `artwork_3d` utilisent l’œuvre centrale ;
- `still` référence un média `image` ;
- `video` référence un média `video` et accepte `source_in_frame` ;
- la section `audio` référence les médias `audio`.

Transitions :

- `cut` relie deux plans consécutifs sans recouvrement ;
- `discover` révèle progressivement un plan d’œuvre depuis un `prologue` ;
- `dissolve` crée un fondu temporel ;
- `manual_match` raccorde un plan de l’œuvre à une photo ou une vidéo réelle et
  conserve tous ses réglages éditables dans le projet.
- `spatial_match` résout l’homographie entre l’œuvre canonique et une photo réelle,
  puis conserve cette transformation pour les raccords et les régions sémantiques.

Le nombre total de frames est la somme des durées des plans. Une transition visuelle
utilise des poignées autour de sa coupe sans modifier cette durée ; une coupe franche
passe directement au plan suivant. L’exemple de référence V3 dure 21 secondes à 30 FPS.

Un prologue conserve son titre, sous-titre, placement, typographie, couleurs et mouvement
dans la recette. La famille `builtin-sans` est embarquée par le renderer local et ne
dépend d’aucun service externe.

## Régions et actions sémantiques

Une région manuelle peut être déclarée dans l’espace normalisé de l’œuvre. Son masque
est copié ou généré dans `assets/semantic`, puis le raccord spatial le projette sur la
photo réelle :

```json
{
  "semantic_regions": [
    {
      "id": "profile-eye",
      "type": "eye",
      "label": "Œil du visage de profil",
      "bounds": [0.118, 0.335, 0.050, 0.095],
      "mask": {"shape": "ellipse", "feather": 0.045}
    }
  ],
  "semantic_actions": [
    {
      "id": "final-blink",
      "capability": "region.blink",
      "target": "profile-eye",
      "trigger": {"event": "shot_end", "shot": "mur3"},
      "parameters": {
        "close_frames": 6,
        "hold_frames": 2,
        "open_frames": 10,
        "intensity": 1.0,
        "easing": "ease-in-out"
      }
    }
  ]
}
```

Le projet persiste la région, son masque, la provenance de l’analyse, l’action et son
trigger. Le compositeur ne modifie que les pixels couverts par la région projetée. La
stratégie de détection automatique est décrite dans `studio-semantic-regions.md`.

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
