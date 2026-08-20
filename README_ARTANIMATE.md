# ArtAnimate

ArtAnimate transforme une œuvre graphique statique en film de construction : les familles de couleurs apparaissent dans l’ordre chromatique, comme du sable qui tombe ou une vague qui dépose la matière. Le rendu est déterministe, fidèle à l’image source et réutilisable sur toute une série d’œuvres.

Le moteur ne génère pas une approximation de l’œuvre. Il analyse sa palette pour décider **quand** révéler chaque zone, mais les pixels finaux proviennent de l’image originale. La dernière image est donc fidèle à la source.

## Fonctionnalités

- regroupement automatique des couleurs en espace CIELAB ;
- complétion morphologique réglable des aplats pour supprimer les micro-trous ;
- roue chromatique rotative avec séquence numérotée et neutres séparés ;
- effets extensibles par contrat/factory, un module par effet ;
- documentation JSON des effets et paramètres affichée en infobulle ;
- familles chromatiques ordonnées (rouge → orange → jaune → vert → bleu → violet → rose) ;
- détection séparée du fond et des contours sombres ;
- effet `sand` avec accumulation irrégulière et grains en chute ;
- effet `wave` avec front sinusoïdal, turbulence et six directions ;
- effet `rgb_fade` avec montée lumineuse ou construction R → G → B ;
- effet `vertical_halo` avec activation chromatique derrière un rideau lumineux ;
- effet `screenprint` avec dépose séquentielle des couches couleur ;
- effet `contour_laser` qui suit les frontières réellement analysées ;
- effet signature `screenprint_laser` : sérigraphie couleur, puis contours noirs au laser ;
- contours au début, à la fin ou pendant toute l’animation ;
- studio 3D cinématique avec pièce vide, meuble en noyer, œuvre couchée, ombre de contact et suspension oscillante ;
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

Le client accepte le glisser-déposer de l’image et du dossier de destination. Chaque modification d’un effet ou de ses paramètres déclenche, après un court délai, un prérendu animé basse définition calculé sans encodage vidéo. Quatre panneaux cliquables ouvrent des fenêtres dédiées — Effet, Couleurs, Analyse et Vidéo — afin de ne jamais empiler tous les paramètres. Chaque valeur numérique dispose d’un slider, de sa valeur exacte et de bornes visibles. La roue chromatique profite d’une grande fenêtre dédiée et se fait tourner à la souris pour choisir la couleur de départ et le sens de progression. Le profil **Studio** ajoute automatiquement easing, exposition temporelle sur trois sous-images et encodage optimisé pour les aplats colorés ; le profil Rapide reste disponible pour les essais.

Les vidéos terminées alimentent une bande historique compacte sous l’atelier : vignette, effet, date, lecture, sélection dans l’Explorateur Windows et suppression confirmée. Les menus **Fichier**, **Génération**, **Réglages**, **Affichage** et **Historique** regroupent les actions et raccourcis. L’onglet **Studio 3D** charge un vrai moteur de scène à la demande : l’effet se choisit et se règle directement dans le Studio, puis l’animation devient la matière de l’œuvre posée sur le meuble avec lampe et éclairage de pièce. Chaque grain de sable 3D reprend un pixel, une couleur et un instant de dépôt issus de la même analyse que le rendu 2D. La vague dispose d’un front en relief synchronisé, les halos et lasers deviennent des outils lumineux au-dessus de l’œuvre, et le fondu RGB colore l’éclairage de la pièce. La caméra s’orbite sur 360° par glisser-déposer, se rapproche à la molette, propose une vue satellite animable et reste réglable avec des sliders accessibles. Le cadre affiché est exactement celui de l’export vidéo. Le bouton **Logs** ouvre un journal défilant, filtrable par niveau et composant, avec recherche textuelle.

### Export du Studio 3D

Quatre cadrages caméra sont fournis — œuvre en plongée, meuble en trois quarts, plan large et satellite avec orbite 360° — puis restent entièrement ajustables. Le nombre de tours de caméra pendant la vidéo est lui aussi réglable. Le cadre de sortie accepte **16:9**, **1:1** et **9:16** ; les définitions Brouillon, HD et Full HD conservent toujours le grand côté attendu, y compris en vertical. La génération reprend la durée, la fluidité, la qualité et tous les paramètres de l’effet 2D, encode en MP4, MOV ou WebM, puis ajoute la vidéo 3D à la même banque historique. Une annulation nettoie automatiquement le fichier partiel.

Une couleur de bord saturée ou trop minoritaire est animée avec l’œuvre : elle n’est jamais étalée artificiellement sur toute l’image d’ouverture.

Lorsqu’une entrée n’est plus logique — image déplacée, dossier supprimé, accès refusé, disque plein, image corrompue ou nom interdit par Windows — l’interface met la zone concernée en rouge et explique en français ce qui s’est passé et quoi faire. Les détails techniques restent disponibles séparément pour le diagnostic.

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
--shape-completion 2        complétion des formes, de 0 à 4
--neutral-position last     neutres avant ou après les couleurs
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

## Architecture extensible

La séparation entre séquence, effet de matière et présentation 2D/3D est détaillée dans [docs/architecture.md](docs/architecture.md).
