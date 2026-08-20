# Architecture ArtAnimate

ArtAnimate sépare la séquence chromatique, l’effet de matière et la présentation vidéo.

## 1. Séquence chromatique

La séquence décide **quand** chaque famille de couleurs apparaît. La roue chromatique,
son sens, son angle de départ et la position des neutres appartiennent à cette couche.
Tous les effets par couches déclarent la capacité `chromatic_sequence`; `rgb_fade`
utilise son propre compositeur d’image complète.

Les capacités `strict_sequence` et `outline_finale` expriment deux contraintes métier
sans créer de branche par nom d’effet dans le renderer. Le mode signature peut ainsi
terminer toutes les couleurs avant d’autoriser la passe des contours noirs.

## 2. Contrat d’effet

Chaque effet vit dans son propre fichier sous `artanimate/core/effects/` et implémente
`AnimationEffect`. La factory est l’unique registre public.

```text
clé de configuration
  → factory create_effect()
  → EffectContext immuable
  → AnimationEffect.create_field()
  → champ de révélation normalisé [0, 1]
  → composition fidèle par ArtworkRenderer
  → décoration transitoire validée (optionnelle)
```

Un effet peut uniquement produire un champ, composer une frame complète avec
`frame_compositor`, ou ajouter un outil lumineux avec `frame_decorator`. Le contrat
valide dimensions et type RGB `uint8`. `ArtworkRenderer` retourne toujours la source
exacte à la fin, les halos et lasers ne pouvant donc altérer l’œuvre finale.

Pour ajouter un effet :

1. créer un module dédié dans `artanimate/core/effects/` ;
2. hériter de `AnimationEffect` et implémenter `build_field()` ;
3. déclarer capacités et champs de configuration ;
4. implémenter `decorate_frame()` si `frame_decorator` est déclaré ;
5. utiliser `@register_effect` et importer le module dans `effects/__init__.py` ;
6. documenter exactement les paramètres dans `assets/docs/effects.fr.json`.

La factory refuse au démarrage un décorateur non implémenté ou une divergence entre
le code et le JSON. L’interface fabrique automatiquement sliders, choix et infobulles.

## 3. Présentation 2D et Studio 3D

`ArtworkRenderer` produit les textures animées utilisées à la fois par l’export 2D et
par la scène Qt Quick 3D. Cette scène existe aujourd’hui : pièce vide, meuble en noyer,
œuvre horizontale, ombre de contact, suspension oscillante et caméra orbitale.

Le Studio propose quatre presets, dont un satellite animé sur 360°, plus les réglages
d’azimut, élévation, distance, nombre de tours et lumière. Le cadre affiché correspond
au ratio réellement capturé par l’encodeur MP4, MOV ou WebM.

Pour le sable, `build_studio_scene_data()` échantillonne uniquement les masques analysés.
Chaque grain conserve les coordonnées normalisées du pixel source, sa couleur RGB exacte
et le temps de dépôt obtenu en inversant la même courbe quintique que le renderer. Le
prérendu et l’export final reçoivent ces mêmes données via leurs workers respectifs.

Les effets de lumière restent synchronisés avec la chronologie des passes. Pour un effet
strict, la scène reçoit le nombre de stages et l’index du contour final afin que l’outil
3D distingue la sérigraphie de la passe laser.

## 4. Atelier desktop et coût du prérendu

L’interface ne lance pas FFmpeg lorsqu’un réglage change. Après un debounce, un worker
annulable analyse une version plafonnée à 384 px et compose 24 images en mémoire. Les
changements plus récents invalident les résultats obsolètes ; le thread graphique ne
fait que lire la boucle reçue.

Une génération n’entre dans l’historique qu’après la réussite de l’encodage final. La
banque conserve un manifeste JSON atomique, les paramètres et une vignette limitée à
480 × 270 px. Elle référence la vidéo dans son dossier de destination et la suppression
reste explicite, confirmée et journalisée.

## 5. Frontière d’erreurs utilisateur

`desktop/problems.py` traduit les exceptions techniques en `UserProblem` : code stable,
titre, explication, récupération et détails séparés. Les chemins sont validés avant le
lancement puis à nouveau dans les workers. L’encodeur ne recrée jamais silencieusement
un dossier disparu ; l’interface explique le problème tandis que les logs conservent la
cause complète.
