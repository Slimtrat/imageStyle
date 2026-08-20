# Architecture ArtAnimate

ArtAnimate sépare volontairement trois décisions qui évoluent indépendamment.

## 1. Séquence chromatique

La séquence décide **quand** chaque famille de couleurs apparaît. La roue chromatique,
son sens, son angle de départ et la position des neutres appartiennent à cette couche.
Ils ne sont pas des effets. Les effets Sable et Vague déclarent tous deux la capacité
`chromatic_sequence` dans leur contrat.

## 2. Effet de matière

Un effet décide **comment** une couche devient visible. Chaque effet vit dans son propre
fichier sous `artanimate/core/effects/` et implémente `AnimationEffect`.

Le cycle est le suivant :

```text
clé de configuration
  → factory create_effect()
  → EffectContext immuable
  → AnimationEffect.create_field()
  → champ de révélation normalisé [0, 1]
  → composition fidèle par ArtworkRenderer
```

Pour ajouter un effet :

1. créer un module dédié dans `artanimate/core/effects/` ;
2. hériter de `AnimationEffect` et implémenter `build_field()` ;
3. déclarer les capacités et les champs de configuration ;
4. utiliser `@register_effect` ;
5. importer le module dans `effects/__init__.py` ;
6. ajouter sa documentation et son schéma de paramètres dans
   `artanimate/assets/docs/effects.fr.json`.

La factory vérifie au démarrage que le code et la documentation JSON décrivent les
mêmes paramètres. L’interface construit ensuite automatiquement les contrôles et les
infobulles depuis ce JSON.

## 3. Présentation vidéo

La présentation décide **où et comment** l’animation est filmée. Elle est distincte de
l’effet : un même rendu Sable ou Vague doit fonctionner en 2D directe et dans une scène
3D sans duplication.

Aujourd’hui, `ArtworkRenderer` fournit directement les frames 2D et respecte le contrat
`FrameSource` utilisé par l’encodeur vidéo.

La V2 ajoutera une factory de présentations avec au moins :

- `direct_2d` : l’œuvre animée remplit le cadre ;
- `room_3d` : l’œuvre devient une texture animée dans une pièce légèrement éclairée.

La scène `room_3d` comportera une table, un cadre ou support d’œuvre, une lampe locale,
une lumière ambiante contrôlée et une caméra déplaçable. Ses paramètres seront séparés :

- azimut, élévation, distance et focale de la caméra ;
- position, température et intensité de la lampe ;
- exposition ambiante et matériaux de la pièce ;
- placement, inclinaison et dimensions de l’œuvre ;
- mouvement de caméra éventuel entre une pose de départ et une pose d’arrivée.

Le renderer 3D consommera les frames de `ArtworkRenderer` comme texture, composera la
scène, puis exposera à son tour `FrameSource`. L’encodeur et les effets resteront donc
inchangés.


## Atelier desktop et coût du prérendu

L’interface ne lance pas FFmpeg lorsqu’un réglage change. Après un debounce, un worker
annulable analyse une version plafonnée à 384 px et compose 20 images en mémoire. Les
changements plus récents invalident les résultats obsolètes ; le thread graphique ne
fait que lire la boucle d’images reçue.

Une génération n’entre dans l’historique qu’après la réussite de l’encodage final. La
banque conserve un manifeste JSON atomique, les paramètres et une vignette limitée à
480 × 270 px. Elle référence la vidéo dans son dossier de destination au lieu de la
dupliquer. La suppression du fichier reste une action explicite, confirmée et journalisée.

Le client expose déjà un onglet `Studio 3D · Coming soon`, mais aucun contrôle 3D ne sera
activé avant l’existence de la factory de présentations et du renderer `room_3d` décrits
ci-dessus.
