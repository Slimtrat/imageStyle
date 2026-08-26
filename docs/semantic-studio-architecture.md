# Artanimate — Architecture du Studio sémantique

Statut : **décision d'architecture retenue** — 26 août 2026.

Cette architecture concerne uniquement le client Python local. Elle organise la
migration du Studio V3 existant sans réécrire les moteurs 2D et 3D. Les noms de
modèles, fournisseurs ou outils externes ne font jamais partie du modèle métier.

## 1. Promesse produit

Artanimate part de l'œuvre, construit une représentation de ce qu'elle contient,
propose ce qui peut raisonnablement y être mis en mouvement, puis orchestre ces
actions dans une timeline.

```text
Œuvre
  │
  ▼
Analyse ───────► Scène sémantique
                    │
                    ▼
                Affordances
                    │
                    ▼
                Capabilities
                    │
                    ▼
       Invocations dans la timeline
                    │
                    ▼
              Plan de rendu
                    │
                    ▼
         Renderers locaux interchangeables
                    │
                    ▼
              Preview / Reel final
```

La timeline est une grammaire de mise en scène. Elle n'est pas le centre métier :
le centre reste l'œuvre et les possibilités que le Studio peut en déduire.

## 2. Règle de dépendance

```text
UI PySide6
   │
   ▼
Application Studio (commandes, orchestration, sessions)
   │
   ▼
Domaine sémantique (Scene, Affordance, Capability, Invocation)
   │
   ├──────────────► Ports de rendu
   │                    ▲
   │                    │
   └──────────────► Adapters 2D / 3D / média / audio
```

- Le domaine ne dépend ni de PySide6, ni de NumPy, ni d'un modèle IA, ni d'un
  moteur de rendu concret.
- L'UI ne choisit pas un renderer directement. Elle crée une invocation de
  capability et peut afficher le renderer retenu ou laisser le choix automatique.
- Un renderer reçoit une requête résolue ; il ne décide pas ce qui existe dans
  l'œuvre.
- Les adapters connaissent l'existant. L'existant ne doit pas connaître tous les
  futurs plugins.
- Le preview et l'export consomment le même plan de rendu et les mêmes sources
  adressables.

## 3. Modules et frontières de travail

```text
artanimate/studio/semantic/
  scene.py          Scene, SceneObject, SceneRelation, ResourceRef
  affordances.py    Affordance, AffordanceSet
  capabilities.py   CapabilityDescriptor, Requirement, ParameterSpec
  invocations.py    CapabilityInvocation, TimelineTrigger
  registry.py       CapabilityRegistry, RendererRegistry, résolution
  rendering.py      RenderRequest, RenderConstraints, renderer ports

artanimate/studio/adapters/
  legacy_project.py clips V1 → invocations
  classic_2d.py     ArtworkRenderer et effets existants
  studio_3d.py      scène 3D adressable
  media.py          images et vidéos locales
  audio.py          piste audio locale

artanimate/studio/
  model.py          document persistant versionné
  timeline.py       opérations éditoriales pures
  compositor.py     exécution d'un plan de rendu résolu
```

Ces frontières sont aussi des frontières de parallélisation : une fois les
contrats du dossier `semantic` gelés, les adapters peuvent avancer sans modifier
leur code mutuellement.

## 4. Scene : ce qui existe dans l'œuvre

Les identifiants et types sont des chaînes extensibles et éventuellement
namespacées. Il n'existe pas d'enum exhaustive des objets possibles.

```python
@dataclass(frozen=True, slots=True)
class ResourceRef:
    resource_id: str
    kind: str                 # mask, depth, image, landmarks…
    metadata: JsonObject

@dataclass(frozen=True, slots=True)
class SceneObject:
    object_id: str
    semantic_type: str        # artwork, camera, human, object, background…
    label: str
    confidence: float
    bounds: Bounds | None
    resource_refs: tuple[ResourceRef, ...]
    attributes: JsonObject
    affordances: tuple[Affordance, ...]

@dataclass(frozen=True, slots=True)
class SemanticScene:
    scene_id: str
    artwork_asset_id: str
    objects: tuple[SceneObject, ...]
    relations: tuple[SceneRelation, ...]
    analyzer_provenance: tuple[AnalyzerRun, ...]
```

Les pixels, masques et depth maps ne sont pas insérés dans le JSON. Le projet
stocke des `ResourceRef` vers des assets locaux contrôlés par le registre d'assets.
Une scène minimale doit toujours pouvoir être créée sans modèle : `artwork`,
`background` et `camera` suffisent pour utiliser les capacités actuelles.

## 5. Affordance : ce qui est possible

Une affordance est un fait exploitable, pas une animation et pas une classe
d'objet fermée.

```python
@dataclass(frozen=True, slots=True)
class Affordance:
    affordance_id: str        # movable, deformable, depth-aware…
    confidence: float
    parameters: JsonObject
    source: str               # manuel, analyzer.local.v1, plugin…
```

Exemple : un ballon peut exposer `movable`, `deformable`, `wind-reactive` et
`frame-exitable`. Une autre catégorie d'objet pourra exposer les mêmes affordances
et bénéficier des mêmes capabilities.

## 6. Capability : ce que l'utilisateur peut demander

Une capability est uniquement une description métier stable.

```python
@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    capability_id: str        # reveal.chromatic, camera.inspect, object.move…
    label: str
    category: str             # reveal, camera, object, audio…
    requirements: tuple[CapabilityRequirement, ...]
    parameters: tuple[CapabilityParameter, ...]
    renderer_candidates: tuple[str, ...]
    emitted_events: tuple[str, ...]
```

Un `CapabilityRequirement` peut demander un type sémantique, une ou plusieurs
affordances, une ressource telle qu'un masque, ou une propriété du projet. Le
registre teste ces exigences sur la scène et retourne une décision explicable :
disponible, indisponible, ou disponible après une analyse complémentaire.

Le type `EffectCapability` déjà présent dans `core.effects` décrit des facultés
techniques internes aux anciens effets. Il reste distinct du concept métier
`CapabilityDescriptor` pendant la migration.

## 7. Invocation : ce que le projet demande réellement

```python
@dataclass(frozen=True, slots=True)
class CapabilityInvocation:
    invocation_id: str
    capability_id: str
    target_id: str | None
    start_frame: int
    duration_frames: int
    parameters: JsonObject
    renderer_policy: RendererPolicy
```

`RendererPolicy` peut être `automatic`, `pinned` ou `fallback-chain`. Le projet
conserve l'intention (`object.exit_frame`) même si l'implémentation change.

À terme, un clip de timeline référence une invocation. Pendant la migration, un
adapter produit une invocation à partir d'un `ClipKind` V1 sans modifier le fichier
source de l'utilisateur.

## 8. Renderer : comment l'intention devient des frames

```python
class CapabilityRenderer(Protocol):
    descriptor: RendererDescriptor

    def evaluate(
        self,
        request: RenderRequest,
    ) -> RendererEvaluation: ...

    def prepare(
        self,
        request: RenderRequest,
        context: RenderContext,
    ) -> PreparedRender: ...

class PreparedRender(Protocol):
    width: int
    height: int
    fps: int
    frame_count: int

    def frame_at(self, frame_index: int) -> RenderLayer: ...
    def close(self) -> None: ...
```

`RenderLayer` porte une image RGB/RGBA et, si nécessaire, un alpha ou des données
audio. Le domaine ne dépend pas de NumPy ; les adapters locaux peuvent l'utiliser.

La sélection d'un renderer tient compte de contraintes explicites : disponibilité
locale, déterminisme, résolution, alpha, coût, mémoire, qualité et préférence de
l'utilisateur. L'absence d'un renderer produit une erreur explicable, jamais un
changement silencieux de capability.

## 9. Registry et plan de rendu

```text
SemanticScene + CapabilityInvocation + RenderConstraints
                         │
                         ▼
                 CapabilityRegistry
                         │ valide cible + paramètres
                         ▼
                   RendererRegistry
                         │ classe les candidats
                         ▼
                    RenderPlanner
                         │ fige la décision
                         ▼
                      RenderPlan
                         │
             ┌───────────┴───────────┐
             ▼                       ▼
         Preview proxy            Export final
```

Un `RenderPlan` est immuable pour une session. Il fige les versions de
capabilities, les renderers retenus, les ressources et les seeds. Deux appels de
`frame_at(n)` dans une même session doivent rendre la même frame.

Les registries sont construits au démarrage de l'application, puis figés pour la
session. Un plugin enregistre des contributions ; il ne modifie pas directement
l'UI, le projet ou le compositeur.

## 10. Events

Les événements relient des invocations sans exposer un graphe technique à
l'utilisateur.

```python
@dataclass(frozen=True, slots=True)
class TimelineTrigger:
    trigger_id: str
    source_invocation_id: str
    event_id: str             # completed, object_exited, beat…
    action_invocation_id: str
    offset_frames: int = 0
```

Le compilateur de timeline résout ces déclenchements en positions de frames avant
le rendu. Les cycles, cibles absentes et événements inconnus sont refusés lors de
la validation du projet.

## 11. Migration du Studio existant

La migration suit une stratégie **expand → adapt → switch → contract**.

### 11.1 Expand

1. Ajouter le domaine `semantic` sans toucher aux algorithmes existants.
2. Fournir une scène minimale pour toute œuvre déjà chargée.
3. Enregistrer un petit catalogue natif de capabilities.
4. Ajouter les ports de rendu et le planificateur.

### 11.2 Adapt

Le bridge V1 effectue les correspondances initiales suivantes :

| Existant | Capability cible | Renderer adapter |
|---|---|---|
| `ARTWORK_2D` | `artwork.present` | `classic.artwork.static` |
| `EFFECT_2D` + `rgb_fade` | `reveal.chromatic` | `classic.effect.rgb_fade` |
| `EFFECT_2D` + autre effet | `reveal.<effect>` | `classic.effect.<effect>` |
| `ARTWORK_3D` | `scene.depth_present` | `classic.studio_3d` |
| caméra du clip | `camera.animate` | `classic.camera_2d` |
| `STILL` / `VIDEO` | `media.present` | `local.media` |
| `AUDIO` | `audio.play` | `local.audio` |

Les snapshots `RenderConfig` existants restent la source de vérité de leurs
parameters : l'adapter les traduit, il ne recalcule pas les choix de l'utilisateur.

### 11.3 Switch

1. Le `CapabilityRegistry` alimente la bibliothèque du Studio.
2. Le `RenderPlanner` remplace progressivement les branches sur `ClipKind`.
3. Le compositeur consomme des `PreparedRender` quelle que soit leur origine.
4. La persistance passe à un schéma V2 avec scène et invocations explicites.

### 11.4 Contract

Les anciennes branches ne sont retirées que lorsque :

- tous les projets V1 sont migrés et round-trippés par tests ;
- chaque effet 2D existant possède un adapter ;
- le Studio 3D est adressable et annulable ;
- preview et export ont des golden frames communes ;
- l'EXE packagé ouvre un projet V1 et produit le même Reel.

Les onglets Atelier 2D et Studio 3D restent accessibles jusqu'à cette preuve.

## 12. Évolution du document projet

Le schéma V1 reste lisible. Le schéma V2 ajoute :

```text
StudioProject
  scene
  invocations[]
  triggers[]
  renderer_preferences
  tracks[]
    clips[]
      invocation_id
      legacy_kind?          # temporaire pendant la migration
```

La migration V1 → V2 est pure, déterministe et sans accès réseau. Les chemins
restent référencés et relinkables. Les données inconnues ne sont jamais supprimées
silencieusement.

## 13. Lots parallélisables

| Lot | Propriétaire de fichiers | Peut démarrer après | Produit attendu |
|---|---|---|---|
| A — Scene | `semantic/scene.py`, `affordances.py` | contrats gelés | graphe validé + scène minimale |
| B — Capabilities | `semantic/capabilities.py`, `registry.py` | contrats gelés | catalogue + explications d'éligibilité |
| C — Rendering | `semantic/rendering.py` | contrats gelés | planner + prepared render lifecycle |
| D — Adapter 2D | `adapters/classic_2d.py` | B + C | tous les effets existants enregistrés |
| E — Adapter 3D | `adapters/studio_3d.py` | B + C | source frame-exact autonome |
| F — Projet V2 | `model.py`, `persistence.py`, bridge legacy | A + B | migration et round-trip |
| G — Studio UI | `desktop/studio*` | A + B | scène, capabilities, properties |
| H — Audio/events | modules dédiés | A + B + C | piste audio et triggers |

Une tâche qui nécessite de modifier simultanément les domaines de trois lots doit
d'abord être découpée ou faire évoluer un contrat de manière explicite.

## 14. Invariants de validation

1. Une œuvre sans analyse automatique crée une scène minimale utilisable.
2. Les types sémantiques, affordances et capabilities sont extensibles par chaîne.
3. Le projet ne référence aucun nom de modèle concret dans le domaine.
4. Une invocation invalide explique l'exigence manquante.
5. Le choix du renderer est reproductible et inspectable.
6. Un même projet, une même seed et une même frame produisent le même résultat.
7. Les projets V1 restent ouvrables et exportables pendant toute la migration.
8. Preview et export partagent le même `RenderPlan`.
9. Annulation et fermeture libèrent workers, GPU, fichiers temporaires et caches.
10. Le Reel final reste entièrement produit dans le client Python local.

## 15. Ce qui n'est pas construit maintenant

- aucun backend ou service cloud ;
- aucun système de plugins universel avant les adapters natifs ;
- aucune taxonomie exhaustive des objets ;
- aucun graphe technique visible façon node editor ;
- aucune dépendance du modèle métier à un modèle IA précis ;
- aucune suppression anticipée des écrans ou formats existants.
