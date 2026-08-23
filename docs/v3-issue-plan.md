# ArtAnimate V3 — Plan d'issues

Statut : brouillon. Les issues GitHub ne sont créées qu'après validation des décisions
listées dans `v3-studio-architecture.md`.

Chaque issue créée devra contenir : objectif utilisateur, périmètre, hors-périmètre,
critères d'acceptation observables, dépendances et tests attendus.

## Milestone 1 — Fondations Studio

1. **Documenter les invariants et le modèle de projet Studio V1**
2. **Implémenter `StudioClock` et les conversions frame/timecode**
3. **Ajouter le contrat `TimedFrameSource` sans casser `FrameSource`**
4. **Implémenter le schéma `StudioProject`, sa validation et ses migrations**
5. **Sauvegarder, autosauvegarder et rouvrir un projet local**
6. **Gérer les assets locaux, les médias manquants et le relink**
7. **Créer le compositeur Studio déterministe et ses golden frames**

## Milestone 2 — Éditeur narratif

8. **Ajouter l'onglet Studio et le canvas Reel 9:16**
9. **Créer le transport et le playhead communs au canvas et à la timeline**
10. **Implémenter la caméra normalisée et sa manipulation directe**
11. **Implémenter les keyframes caméra et les easings**
12. **Créer la piste principale de plans**
13. **Ajouter trim, split, déplacement, duplication et snapping**
14. **Ajouter un historique de commandes undo/redo**
15. **Créer les presets Macro, Inspect, Reveal, Drift et Handheld**
16. **Créer le cache proxy et le preview annulable**

## Milestone 3 — Reel complet V3.0

17. **Adapter `ArtworkRenderer` en source 2D adressable**
18. **Utiliser les effets 2D comme clips ou layers temporels**
19. **Rendre l'état du Studio 3D adressable à une frame donnée**
20. **Adapter le Studio 3D en source de plan V3**
21. **Importer et composer une photo réelle**
22. **Décoder, trimmer et composer une vidéo réelle**
23. **Ajouter les transitions cut et dissolve**
24. **Créer l'alignement manuel et le blend virtuel → réel**
25. **Importer et lire une piste audio synchronisée**
26. **Calculer et afficher la waveform**
27. **Ajouter trim, volume, fade-in et fade-out audio**
28. **Exporter avec audio intégré ou audio de référence exclu**
29. **Créer le parcours guidé éditable `Explore`**
30. **Exporter un Reel 1080 × 1920 à 30 ou 60 FPS**
31. **Intégrer les exports Studio à l'historique existant**
32. **Durcir erreurs, annulation, performance et packaging Windows**
33. **Valider un projet Reel complet dans l'EXE packagé**

## Milestone 4 — Smart Studio V3.1 proposé

34. **Détecter localement les zones d'intérêt d'une œuvre**
35. **Proposer des plans et trajectoires caméra éditables**
36. **Aligner automatiquement une frame virtuelle et une image réelle**
37. **Détecter beats, downbeats et drops dans une piste locale**
38. **Afficher et éditer les marqueurs musicaux**
39. **Créer le système de templates Studio**
40. **Ajouter des modulations musicales optionnelles et bornées**

## Graphe de livraison

```text
1–7 Fondations
  ↓
8–16 Éditeur
  ↓
17–20 Sources 2D/3D ─┐
21–24 Retour réel ───┼─→ 29–33 Reel complet et livraison
25–28 Audio ─────────┘
  ↓
34–40 Smart Studio, si retenu pour V3.1
```

Les milestones 1 et 2 sont des jalons internes. Ils ne constituent pas des versions
produit publiables isolément. La V3.0 exige le parcours de l'issue 33 validé.

