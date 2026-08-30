# Artanimate V3 — Todo de migration vers le Studio sémantique

Source de vérité produit : `docs/semantic-studio-architecture.md`.

Règles : chaque item doit finir avec tests, documentation utile et preuve observable.
Les lots portant le même marqueur `PAR-*` peuvent avancer en parallèle une fois
leurs dépendances cochées. Les anciennes issues 3D/audio/export restent valides,
mais sont subordonnées à cette couche d'abstraction.

## P0 — Geler les contrats sémantiques

- [x] **ARCH-01** Définir Scene → Affordance → Capability → Invocation → Renderer.
- [x] **ARCH-02** Définir la migration expand/adapt/switch/contract du schéma V1.
- [x] **ARCH-03** Définir les frontières de parallélisation et propriétaires de fichiers.
- [x] **CORE-01** Créer les types immuables JSON-safe du graphe de scène. `[PAR-A]`
- [x] **CORE-02** Créer Affordance et la validation des identifiants extensibles. `[PAR-A]`
- [x] **CORE-03** Créer CapabilityDescriptor, requirements et parameter specs. `[PAR-B]`
- [x] **CORE-04** Créer CapabilityInvocation et RendererPolicy. `[PAR-B]`
- [x] **CORE-05** Créer les ports RenderRequest/PreparedRender et leur lifecycle. `[PAR-C]`
- [x] **CORE-06** Créer CapabilityRegistry et RendererRegistry figés par session. `[PAR-B]`
- [x] **CORE-07** Créer RenderPlanner avec décisions explicables et déterministes. `[PAR-C]`
- [x] **CORE-08** Tester sérialisation, validation, extension par chaînes et erreurs métier.

Critère de fin P0 : un test construit une scène minimale, découvre une capability,
sélectionne un faux renderer et obtient un plan immuable sans importer PySide6.

## P1 — Migrer l'existant sans le réécrire

- [x] **MIG-01** Créer automatiquement `artwork`, `background` et `camera` pour un projet V1.
- [x] **MIG-02** Mapper les clips V1 vers des invocations sans modifier le projet source.
- [x] **MIG-03** Enregistrer `artwork.present` et l'adapter statique. `[PAR-D]`
- [x] **MIG-04** Enregistrer chaque effet actuel comme `reveal.*`. `[PAR-D]`
- [x] **MIG-05** Adapter `ArtworkRenderer` en PreparedRender frame-exact. `[PAR-D]`
- [x] **MIG-06** Adapter la caméra 2D comme capability indépendante. `[PAR-D]`
- [x] **MIG-07** Déplacer l'état 3D adressable derrière `classic.studio_3d`. `[PAR-E]`
- [x] **MIG-08** Fournir une capture 3D autonome, retryable et annulable. `[PAR-E]`
- [x] **MIG-09** Faire exécuter les adapters par le compositeur sans branche métier 2D/3D.
- [x] **MIG-10** Comparer les golden frames legacy et adapter pour tous les effets livrés.

Critère de fin P1 : le projet démo actuel produit les mêmes frames par le chemin
legacy et par le RenderPlan sémantique, y compris après un seek arrière.

## P2 — Faire évoluer le document Studio

- [x] **DOC-01** Spécifier puis implémenter le schéma Studio V2.
- [x] **DOC-02** Ajouter SemanticScene, invocations, triggers et préférences renderer.
- [x] **DOC-03** Écrire la migration pure V1 → V2.
- [x] **DOC-04** Garantir le round-trip JSON et conserver les snapshots RenderConfig.
- [x] **DOC-05** Ouvrir, relinker et exporter un projet V1 depuis le code V2.
- [x] **DOC-06** Ajouter fixtures de projets réels V1/V2 et tests de non-régression.

Critère de fin P2 : aucun projet existant n'est perdu ou modifié silencieusement et
un document V2 conserve l'intention même si le renderer préféré est absent.

## P3 — UI artwork-first du Studio

- [x] **UI-01** Ajouter l'arbre Scene avec œuvre, objets, fond et caméra. `[PAR-G]`
- [x] **UI-02** Afficher les capabilities compatibles pour la sélection. `[PAR-G]`
- [x] **UI-03** Expliquer les capabilities indisponibles et analyses manquantes. `[PAR-G]`
- [x] **UI-04** Remplacer la bibliothèque « FX 2D/3D » par catégories métier. `[PAR-G]`
- [x] **UI-05** Éditer les paramètres typés d'une invocation dans Properties. `[PAR-G]`
- [x] **UI-06** Afficher le renderer automatique ou épinglé sans exposer un graphe technique.
- [x] **UI-07** Garder Atelier 2D et Studio 3D accessibles pendant la migration.

Critère de fin P3 : l'utilisateur sélectionne l'œuvre ou un objet, voit ce qui peut
bouger, ajoute l'action à la timeline et la modifie sans choisir un « effet 2D/3D ».

## P4 — Analyse locale et premières affordances

- [x] **SCAN-01** Créer le port SceneAnalyzer et la provenance des résultats. `[PAR-A]`
- [x] **SCAN-02** Implémenter l'analyse minimale sans modèle. `[PAR-A]`
- [x] **SCAN-03** Ajouter sélection/masque manuel comme ressource de scène. `[PAR-A]`
- [x] **SCAN-04** Ajouter foreground/background/depth localement. `[PAR-A]`
- [x] **SCAN-05** Déduire movable, frame-exitable et depth-aware avec confiance.
- [x] **SCAN-06** Mettre en cache et invalider les analyses selon le fingerprint de l'œuvre.

Critère de fin P4 : une œuvre arbitraire reste utilisable sans scan avancé et une
analyse enrichie ajoute des possibilités sans changer le format des capabilities.

## P5 — Premières capabilities sémantiques

- [x] **SEM-01** `object.move` déterministe avec masque manuel. `[PAR-D]`
- [x] **SEM-02** `object.exit_frame` avec événements `started/completed/object-exited`. `[PAR-D]`
- [x] **SEM-03** `scene.parallax` basé sur depth/layers. `[PAR-E]`
- [x] **SEM-04** `camera.inspect` et `camera.zoom_out` sur la même œuvre. `[PAR-E]`
- [x] **SEM-05** `environment.particles` ciblé sur scène ou objet. `[PAR-D]`
- [x] **SEM-06** Dégrader proprement quand masque/depth/renderer manque.

Critère de fin P5 : un objet sélectionné quitte réellement l'œuvre dans un clip
contrôlable, combiné à une caméra et un reveal existant.

## P6 — Events, audio et mise en scène

- [x] **EVT-01** Ajouter TimelineTrigger et validation acyclique. `[PAR-H]`
- [x] **EVT-02** Compiler les événements déterministes en frames. `[PAR-H]`
- [x] **AUD-01** Importer/décoder une piste audio locale frame-synchronisée. `[PAR-H]`
- [x] **AUD-02** Afficher waveform, trim, volume et fades. `[PAR-H]`
- [ ] **AUD-03** Ajouter markers, sections et BeatMap éditable. `[PAR-H]`
- [ ] **AUD-04** Déclencher une invocation sur marker/beat/drop. `[PAR-H]`
- [x] **AUD-05** Muxer ou exclure l'audio de référence sans changer le montage.

Critère de fin P6 : la fin d'une action et un marqueur audio peuvent déclencher deux
actions synchronisées, reproduites à l'identique en preview et à l'export.

## P7 — Médias réels et Reel fini

- [x] **REAL-01** Adapter image locale et vidéo frame-exact derrière `media.present`.
  - [x] **REAL-01A** Image locale frame-exact, cadrable et diagnostiquable.
  - [x] **REAL-01B** Vidéo locale frame-exact, décodable et trimmable.
- [x] **REAL-02** Ajouter cut, dissolve et blend virtuel → réel.
- [x] **REAL-03** Ajouter alignement manuel œuvre/photo réelle.
- [x] **REAL-04** Construire le parcours éditable Explore.
- [x] **EXP-01** Exporter 1080×1920 à 30/60 FPS par le RenderPlan commun.
- [x] **EXP-02** Intégrer historique, annulation, reprise d'erreur et nettoyage atomique.
- [x] **EXP-03** Borner caches CPU/GPU et fermer tous les workers.
- [x] **PKG-01** Embarquer les dépendances locales dans le gros EXE Windows accepté.
- [ ] **PKG-02** Valider un Reel complet dans l'EXE packagé.

Critère de fin P7 : œuvre → mise en scène sémantique + 2D + 3D → transition réelle
→ audio → MP4 Reel fini, testé de bout en bout sur Windows.

## Backlog après stabilisation native

- [ ] **PLUG-01** Extraire PluginManifest/PluginContext à partir des besoins réels.
- [ ] **PLUG-02** Charger et diagnostiquer des plugins locaux versionnés.
- [ ] **GEN-01** Ajouter les renderers génératifs derrière les mêmes capabilities.
- [ ] **GEN-02** Gérer coût, VRAM, progression, annulation et fallback explicite.
- [ ] **CLEAN-01** Retirer les branches legacy uniquement après toutes les preuves P1–P7.
