# ArtAnimate V3 — Architecture du Studio local

Statut : brouillon de décision. Cette architecture concerne exclusivement le client
Python local. Elle n'introduit ni serveur, ni API distante, ni base de données, ni
compte utilisateur, ni stockage cloud.

## Résultat produit attendu

La V3 doit permettre de produire, dans l'application Windows, un Reel vertical fini :

1. importer une œuvre ;
2. construire plusieurs plans ;
3. animer une caméra au-dessus de l'œuvre ;
4. appliquer ponctuellement les moteurs 2D et 3D existants ;
5. terminer sur une photo ou une vidéo réelle ;
6. monter avec une piste audio locale ;
7. prévisualiser puis exporter le même montage en 1080 × 1920.

La V3 n'est considérée comme livrée que lorsque ce parcours fonctionne de bout en
bout dans l'exécutable packagé.

## Contraintes invariantes

- Tous les calculs et tous les médias restent sur la machine.
- L'œuvre source demeure fidèle dans la frame finale.
- Le preview et l'export consomment le même modèle de projet et le même compositeur.
- Un projet rouvert doit reproduire le même montage et les mêmes frames.
- Les onglets Atelier 2D et Studio 3D restent fonctionnels.
- Les changements de montage sont annulables et ne modifient pas les médias source.
- Une annulation ou une erreur ne laisse pas d'export partiel présenté comme terminé.

## Architecture cible

```text
PySide6 MainWindow
  ├─ Atelier 2D existant
  ├─ Studio 3D existant
  └─ Studio V3
       ├─ Canvas 9:16
       ├─ Transport
       ├─ Inspecteur
       └─ Timeline
            │
            ▼
       StudioProject (dataclasses + JSON versionné)
            │
            ▼
       StudioClock (temps ↔ frame)
            │
            ▼
       StudioCompositor.frame_at(frame_index)
         ├─ Artwork2DSource
         ├─ Studio3DSource
         ├─ StillImageSource
         ├─ VideoFileSource
         ├─ CameraTransform
         ├─ EffectLayer
         └─ Transition
            │
            ├─ PreviewWorker + cache local
            └─ VideoFrameEncoder + audio local optionnel
```

Le Studio est une couche d'orchestration. Il ne duplique ni l'analyse chromatique,
ni les effets, ni la scène 3D existante.

## Modèle de projet

Le document JSON est versionné dès sa première version. Les temps éditoriaux sont
stockés en frames dans le FPS du projet afin d'éviter les dérives flottantes.

```text
StudioProject
  schema_version
  settings
    width, height, fps, duration
  assets[]
    id, kind, path, fingerprint, metadata
  sequence
    shots[]
    effect_layers[]
    transitions[]
    audio_tracks[]
  export_settings
```

Un `Shot` possède au minimum une source, une plage dans le projet, une plage dans la
source, une caméra et ses transitions. Les paramètres des effets 2D/3D sont copiés
dans le projet : un ancien montage ne change pas lorsque les réglages courants de
l'Atelier changent.

Les chemins de médias sont locaux. Le chargeur conserve assez de métadonnées pour
détecter un fichier déplacé ou remplacé et proposer un relink explicite.

## Temps et sources de frames

Le contrat V2 `FrameSource.frames()` reste disponible pour les exports existants. La
V3 ajoute un contrat adressable, sans casser les consommateurs actuels :

```python
class TimedFrameSource(Protocol):
    width: int
    height: int
    fps: int
    frame_count: int

    def frame_at(self, frame_index: int) -> np.ndarray: ...
```

Les adaptateurs peuvent mettre en cache une analyse ou une séquence coûteuse, mais le
résultat d'un même `frame_index` doit rester déterministe. Le compositeur travaille
toujours dans le repère du projet, puis applique la caméra et les layers actifs.

## Timeline V3.0 proposée

La timeline vise un montage narratif robuste, pas un clone généraliste de Premiere :

- une piste principale ordonnée de plans ;
- des layers d'effets liés à un plan ;
- une piste de transitions ;
- une piste audio de référence ;
- trim, split, déplacement, duplication, snapping et undo/redo.

Cette structure couvre le Reel cible tout en gardant un modèle explicite et testable.

## Preview et export

Le preview demande des frames au compositeur à résolution proxy et les met en cache.
L'export appelle le même compositeur à la résolution finale. Les deux chemins ne
doivent pas réimplémenter les transformations de caméra ou les transitions.

L'export vidéo existant reste incrémental et atomique. Une étape locale de mux audio
est ajoutée lorsque l'utilisateur choisit d'intégrer la musique. Le mode « audio de
référence » exporte la vidéo seule sans perdre les marqueurs de synchronisation du
projet.

## Risques techniques connus

### Rendu 3D adressable

Le Studio 3D actuel envoie séquentiellement les textures au thread GUI puis capture
le framebuffer Qt Quick. La V3 doit séparer l'état de scène de la boucle d'export et
permettre de positionner explicitement l'effet et la caméra à une frame donnée.

### Décodage des vidéos réelles

La lecture interactive Qt Multimedia ne suffit pas nécessairement à garantir un
décodage frame-exact pour le compositeur. Le choix de la dépendance locale ou du
pipeline FFmpeg dépend de la décision sur les bibliothèques embarquées.

### Audio

La waveform, le trim et le mux doivent utiliser une même référence temporelle que la
timeline. L'audio ne doit jamais piloter une horloge indépendante du projet.

## Décisions encore ouvertes

1. V3.0 s'arrête-t-elle au Studio complet avec audio et match manuel, les fonctions
   intelligentes passant en V3.1 ?
2. La timeline structurée proposée est-elle retenue ?
3. Les médias restent-ils référencés à leur emplacement avec relink ?
4. De nouvelles dépendances Python locales peuvent-elles être embarquées ?

