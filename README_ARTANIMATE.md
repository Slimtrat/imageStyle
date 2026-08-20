# ArtAnimate

ArtAnimate transforme une œuvre graphique statique en film de construction : les familles de couleurs apparaissent dans l’ordre chromatique, comme du sable qui tombe ou une vague qui dépose la matière. Le rendu est déterministe, fidèle à l’image source et réutilisable sur toute une série d’œuvres.

Le moteur ne génère pas une approximation de l’œuvre. Il analyse sa palette pour décider **quand** révéler chaque zone, mais les pixels finaux proviennent de l’image originale. La dernière image est donc fidèle à la source.

## Fonctionnalités

- regroupement automatique des couleurs en espace CIELAB ;
- familles chromatiques ordonnées (rouge → orange → jaune → vert → bleu → violet → rose) ;
- détection séparée du fond et des contours sombres ;
- effet `sand` avec accumulation irrégulière et grains en chute ;
- effet `wave` avec front sinusoïdal, turbulence et six directions ;
- contours au début, à la fin ou pendant toute l’animation ;
- export MP4 H.264, MOV ou WebM, sans installation manuelle de FFmpeg ;
- analyse de palette en JSON et planche de contrôle PNG ;
- presets JSON reproductibles et graine aléatoire configurable.

## Installation

Python 3.11 ou plus récent est recommandé.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Pour le développement :

```powershell
python -m pip install -e ".[dev]"
pytest
```

## Client desktop

Installez l’interface puis lancez-la :

```powershell
python -m pip install -e ".[desktop]"
artanimate-ui
```

Le client accepte le glisser-déposer de l’image et du dossier de destination. Il affiche l’œuvre originale, le rendu en cours avec son pourcentage, puis lit la vidéo finale. Les réglages visibles s’adaptent automatiquement au mode Sable ou Vague. Le bouton **Logs** ouvre un journal défilant, filtrable par niveau et composant, avec recherche textuelle. Les événements sont aussi conservés dans un fichier rotatif accessible depuis cette fenêtre.

Vous pouvez aussi le lancer sans commande installée :

```powershell
python -m artanimate.desktop
```

## Exécutable Windows autonome

L’EXE Windows embarque Python, Qt et FFmpeg. La machine de destination n’a donc
besoin ni de Python ni d’une installation séparée de FFmpeg.

```powershell
python -m pip install -e ".[desktop,build]"
.\packaging\windows\build.ps1 -Python "python"
```

Le résultat est créé dans `dist\ArtAnimate.exe`. Il s’agit d’un exécutable unique,
sans fenêtre de console, avec l’icône et les métadonnées de version ArtAnimate.

## Premier film en ligne de commande

```powershell
artanimate render oeuvre.jpg -o oeuvre-sable.mp4
```

Un rendu plus ample en Full HD :

```powershell
artanimate render oeuvre.jpg -o oeuvre-vague.mp4 `
  --effect wave `
  --direction diagonal `
  --width 1920 `
  --duration 14 `
  --outline last `
  --order chromatic
```

Le même outil est disponible sans installer la commande globale :

```powershell
python -m artanimate render oeuvre.jpg -o oeuvre.mp4
```

## Examiner l’analyse avant le rendu

```powershell
artanimate analyze oeuvre.jpg `
  --json analyse.json `
  --preview analyse.png
```

La planche montre l’image redimensionnée et les familles retenues. Le JSON contient la couleur représentative, la teinte, la couverture et l’ordre de passage de chaque couche.

## Réglages utiles

```text
--effect sand|wave
--order chromatic|reverse|area|luminance
--outline first|last|together
--direction left|right|top|bottom|diagonal|radial
--colors 24                 nombre de centres de quantification
--duration 12               durée totale, pauses comprises
--fps 30
--width 1280                largeur de sortie, ratio conservé
--start-hue 0               point de départ de l’ordre chromatique
--background-tolerance 11   tolérance du fond, en Delta E
--outline-luma 36           seuil de luminosité des contours
--seed 7                    rendu strictement reproductible
--config config.json        charge un preset JSON
--manifest rendu.json       sauvegarde les décisions d’analyse
--log-level INFO            DEBUG, INFO, WARNING ou ERROR
--log-file session.log      copie persistante du journal CLI
```

Les options données en ligne de commande prennent le dessus sur le fichier JSON.

Exemple de preset : [examples/cinematic-sand.json](examples/cinematic-sand.json).

## Conseils selon l’image

- Une illustration à aplats fonctionne généralement avec les valeurs par défaut.
- Sur une photo ou une toile texturée, augmenter `--colors` vers 32–40 conserve davantage de nuances.
- Si le blanc du papier apparaît comme une couleur animée, augmenter légèrement `--background-tolerance`.
- Si un bleu très sombre est pris pour un contour, diminuer `--outline-luma`.
- Pour une série cohérente, conserver le même fichier de configuration et la même graine.

## Architecture

```text
image source
  → redimensionnement et détection du fond
  → échantillonnage CIELAB et k-means++
  → fusion en familles chromatiques
  → extraction des contours
  → ordonnancement et animation des masques
  → composition avec les pixels originaux
  → encodage vidéo atomique
```

ArtAnimate traite les images localement. Aucun fichier n’est envoyé vers un service externe.
