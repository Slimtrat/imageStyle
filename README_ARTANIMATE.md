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
- effet `pigment_sweep` : masse organique globale, pigments liés aux vrais pixels, dépassement puis verrouillage exact ;
- effet `wave` avec front sinusoïdal, turbulence et six directions ;
- effet `paint_drop` avec grosse goutte verticale, impact ciblé sur le vrai masque et remplissage liquide ;
- effet `rgb_fade` avec montée lumineuse ou construction R → G → B ;
- effet `vertical_halo` avec un rideau unique qui ne révèle que la partie déjà traversée ;
- effet `screenprint` avec dépose séquentielle des couches couleur ;
- effet `contour_laser` avec détection de formes, chemins continus et rayon vertical exactement aligné ;
- effet signature `screenprint_laser` : sérigraphie couleur sans coutures visibles, puis contours noirs au laser ;
- contours au début, à la fin ou pendant toute l’animation ;
- studio 3D cinématique avec pièce vide, meuble en noyer, œuvre couchée, ombre de contact et suspension oscillante ;
- analyse musicale locale et annulable : tempo, beats, temps forts et drops avec confiance, sensibilité sauvegardée et cache par empreinte audio ;
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

La version installée reste visible dans l’en-tête du client. Le client accepte le glisser-déposer de l’image et du dossier de destination. Chaque modification d’un effet ou de ses paramètres déclenche, après un court délai, un prérendu animé basse définition calculé sans encodage vidéo. Quatre panneaux cliquables ouvrent des fenêtres dédiées — Effet, Couleurs, Analyse et Vidéo — afin de ne jamais empiler tous les paramètres. Chaque valeur numérique dispose d’un slider, de sa valeur exacte et de bornes visibles. La roue chromatique profite d’une grande fenêtre dédiée et se fait tourner à la souris pour choisir la couleur de départ et le sens de progression. Le profil **Studio** ajoute automatiquement easing, exposition temporelle sur trois sous-images et encodage optimisé pour les aplats colorés ; le profil Rapide reste disponible pour les essais.

Les vidéos terminées alimentent une bande historique compacte sous l’atelier : vignette, effet, date, lecture, sélection dans l’Explorateur Windows et suppression confirmée. Les menus **Fichier**, **Génération**, **Réglages**, **Affichage** et **Historique** regroupent les actions et raccourcis. L’onglet **Studio 3D** charge un vrai moteur de scène à la demande : l’effet se choisit et se règle directement dans le Studio, puis l’animation devient la matière de l’œuvre posée sur le meuble avec lampe et éclairage de pièce. Chaque grain de sable 3D reprend un pixel, une couleur et un instant de dépôt issus de la même analyse que le rendu 2D. Pigment Sweep va plus loin : la scène réutilise directement les cibles, couleurs, entrées, boucles et rebonds calculés par le renderer 2D, puis verrouille la texture sur l’œuvre exacte. La vague déforme désormais une grille dense portant la vraie texture : une crête soulève et tord l’œuvre, puis dépose les couleurs strictement derrière elle ; les pigments sombres ou froids avancent plus lentement que les couleurs légères. Le contraste de densité, l’amplitude, la fréquence, la turbulence et le bord progressif restent réglables ; la surface redevient parfaitement plane avant l’image finale. La sérigraphie est matérialisée par une unique ligne blanche sur l’œuvre, sans machine suspendue. Le laser devient un rayon venu du ciel, attaché au plan exact du tableau et piloté par ses contours détectés et par le même curseur temporel que le trait écrit ; le fondu RGB colore l’éclairage de la pièce. Pour le mode WOW, l’outil lumineux partage exactement l’axe et l’easing de l’œuvre ; un badge annonce distinctement l’acte de sérigraphie couleur puis la passe laser des contours noirs. La lumière traverse spatialement toute l’œuvre au lieu de dessiner les limites des masques, tandis qu’une sous-encre temporaire raccorde les aplats jusqu’au passage du laser. La caméra propose désormais un rail Signature centré sur l’œuvre : survol rase-motte en courbe, montée progressive, puis plongée finale verrouillée sur l’image complète. Une dérive lente et une plongée fixe complètent ce mouvement sans remettre la pièce au premier plan. Le cadre affiché est exactement celui de l’export vidéo. Le bouton **Logs** ouvre un journal défilant, filtrable par niveau et composant, avec recherche textuelle.

### Export du Studio 3D

Trois mouvements centrés sur l’œuvre sont fournis — rail Signature rase-motte vers plongée, plongée avec dérive lente et plongée fixe. L’angle, la plongée finale, la distance, l’amplitude du trajet et une rotation douce restent réglables. Le cadrage final recule automatiquement en 9:16 afin de conserver l’œuvre complète. Le cadre de sortie accepte **16:9**, **1:1** et **9:16** ; les définitions Brouillon, HD et Full HD conservent toujours le grand côté attendu, y compris en vertical. La génération reprend la durée, la fluidité, la qualité et tous les paramètres de l’effet 2D, encode en MP4, MOV ou WebM, puis ajoute la vidéo 3D à la même banque historique. Une annulation nettoie automatiquement le fichier partiel.

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

Le build utilise un `PATH` isolé puis lance l’auto-diagnostic du one-file : chargement
de la fenêtre et du Studio, FFmpeg issu du bundle, présence des encodeurs H.264, VP9,
AAC et Opus, puis round-trip H.264. Les rapports `ArtAnimate-build.json` et
`ArtAnimate-self-test.json` consignent la taille, la durée, le hash et le résultat.
Le détail des budgets et de la validation est dans
[docs/studio-production-hardening.md](docs/studio-production-hardening.md).

La qualification produit rejoue ensuite un Reel V3 complet depuis ce même EXE :
projet vertical de 12 secondes, plans caméra 2D/3D, effet, match vers une photo,
musique rognée, sauvegarde/réouverture, exports avec et sans audio et relecture depuis
l’historique.

```powershell
.\packaging\windows\qualify-v3.ps1
```

Le protocole et la revue visuelle sont détaillés dans
[docs/studio-v3-qualification.md](docs/studio-v3-qualification.md).

## Studio programmable et projets portables

Une recette JSON peut maintenant construire sans interface un dossier Studio autonome :
projet `.artanimate` réouvrable, médias copiés en chemins relatifs, recette canonique,
snapshots des versions précédentes, planche de contrôle et export optionnel.

```powershell
artanimate studio build .\transition.json --output .\mon-projet
```

Le même job peut être lancé depuis l’exécutable autonome, sans Python installé :

```powershell
.\ArtAnimate.exe --headless-studio .\transition.json .\mon-projet .\rapport.json
```

À recette et médias identiques, la reconstruction ne crée aucune révision parasite. Si
le contenu change, l’ancien projet complet est archivé avant remplacement atomique. Un
échec conserve la dernière version valide et produit un rapport JSON exploitable.

Le contrat, le schéma et l’exemple `3D → mur3 → mur2` sont décrits dans
[docs/studio-headless.md](docs/studio-headless.md) et
[examples/headless-transition-mur.json](examples/headless-transition-mur.json).

La politique de restitution fidèle des couleurs de l’œuvre 3D et sa mesure ΔE00 sont
décrites dans [docs/studio-color-fidelity.md](docs/studio-color-fidelity.md).

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
--effect sand|pigment_sweep|wave|paint_drop|rgb_fade|vertical_halo|screenprint|contour_laser|screenprint_laser
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
