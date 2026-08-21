# Architecture ArtAnimate

ArtAnimate sépare la séquence chromatique, l’effet de matière et la présentation vidéo.

## 1. Séquence chromatique

La séquence décide **quand** chaque famille de couleurs apparaît. La roue chromatique,
son sens, son angle de départ et la position des neutres appartiennent à cette couche.
Tous les effets par couches déclarent la capacité `chromatic_sequence`; `rgb_fade`
utilise son propre compositeur d’image complète. `pigment_sweep` déclare au contraire
`global_reveal` : il construit un unique masque de premier plan et traverse l’œuvre une
seule fois, indépendamment de la roue chromatique.

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
`frame_compositor`, ou ajouter un outil lumineux/physique avec `frame_decorator`. Le
contexte de champ expose le masque réel de la couche lorsqu’un impact doit viser la
bonne forme. Le contrat
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

Le Studio propose trois mouvements centrés sur l’œuvre. Le rail Signature conserve une
caméra basse pendant 58 % du temps, traverse la matière en courbe, puis interpole vers la
plongée finale entre 58 % et 90 %. Une dérive elliptique lente et une plongée fixe offrent
deux variantes plus sobres. Toutes reviennent à une pose finale stable avant le dernier
hold. La distance de fin tient compte du ratio d’export : en 9:16, elle augmente
automatiquement pour garder l’œuvre horizontale complète dans le cadre capturé.

Pour la Vague, `studio3d_wave.py` traduit le contrat validé de l’effet en une `QQuick3DGeometry` native de 96 × 64 sommets. À la sélection de l’œuvre, le module échantillonne une texture source immuable : luminance, saturation et dominante froide produisent une densité locale lissée. À chaque image, cette densité décale le front, amplifie la hauteur, tord les sommets et allonge la traînée ; les normales sont recalculées pour conserver un éclairage physique. Le `PrincipledMaterial` éprouvé continue d’afficher la texture animée exacte du renderer. La déformation est amortie à partir de 88 % et nulle à 99,5 % afin que la pose finale retrouve une œuvre plane et fidèle.

Pour Pigment Sweep, son module dédié prépare une banque déterministe de pigments ciblés
derrière le contrat `targeted_particles`. Le contrat vérifie les dimensions, les temps,
les cibles dans le masque et l’identité entre chaque couleur transportée et son pixel source.
Chaque entrée contient le pixel destination, sa couleur source exacte, son point d’entrée
hors cadre, son vecteur de dépassement, sa boucle organique et son instant de dépôt. Le
Studio 3D échantillonne directement cette banque : il ne réinvente ni cible ni mouvement.
La texture Studio omet les touches volantes 2D, remplacées par la géométrie physique ;
l’œuvre déjà déposée reste composée avec les pixels source exacts.
La trajectoire approche la destination pendant 78 % du vol, la dépasse puis effectue un
retour amorti ; au dépôt, le grain disparaît et le pixel exact de la texture prend le relais.

Pour le sable, `build_studio_scene_data()` échantillonne uniquement les masques analysés.
Chaque grain conserve les coordonnées normalisées du pixel source, sa couleur RGB exacte
et le temps de dépôt obtenu en inversant la même courbe quintique que le renderer. Le
prérendu et l’export final reçoivent ces mêmes données via leurs workers respectifs.

Les effets de lumière restent synchronisés avec la chronologie des passes. Pour un effet
strict, la scène reçoit le nombre de stages et l’index du contour final afin que l’outil
3D distingue la sérigraphie de la passe laser. L’outil physique hérite de la même
transformation que le plateau de l’œuvre et applique la même courbe quintique que le
renderer : sa position projetée reste donc alignée du premier au dernier pixel.

La découpeuse laser fusionne les frontières des familles de couleur et les traits
noirs, amincit les formes en lignes centrales, sépare les composantes puis construit un
parcours continu. Les déplacements entre formes restent dans la chronologie mais coupent
le faisceau. Le champ de révélation, la tête 2D et le portique XY du Studio consomment ce
même itinéraire échantillonné ; le trait final reste constitué des pixels source exacts.

En 2D, le faisceau est un champ spatial indépendant des masques de segmentation. Les
couleurs déposées créent une sous-encre douce jusque sous le futur contour noir, puis la
passe laser la remplace progressivement. Ce raccord transitoire masque les coutures de
segmentation sans modifier la frame finale, qui reste toujours la source exacte.

Le halo vertical suit un autre contrat visuel : c’est un compositeur global, donc un
seul front sépare à tout instant la partie révélée derrière le halo de la partie encore
cachée devant lui. Pour `paint_drop`, le renderer calcule un pixel d’impact appartenant
réellement à chaque masque. La présentation 2D dessine uniquement la grosse goutte et
son impact ; la texture Studio les omet et laisse la scène 3D afficher cette matière comme
géométrie physique. Aucun outil persistant ne change brutalement de position entre deux
couches. La texture animée désactive aussi les mipmaps afin de préserver des limites nettes.

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
