# Parcours Explore

Explore est un point de départ éditorial de 12 secondes, pas un moteur de rendu ni
un template opaque. Sa création remplace la timeline courante en une seule opération
annulable et produit uniquement des champs standards de `StudioProject`.

## Découpage par défaut

| Plan | Durée à 30 FPS | Intention |
| --- | ---: | --- |
| Macro | 75 frames / 2,5 s | Entrer dans une zone choisie de l’œuvre. |
| Inspection | 90 frames / 3 s | Parcourir une seconde zone choisie. |
| Reveal | 105 frames / 3,5 s | Revenir sur l’œuvre entière et y rester. |
| Réel | 90 frames / 3 s | Inviter au choix d’une photo ou vidéo locale. |

À 60 FPS, les durées sont doublées. Trois fondus de 0,4 seconde relient les plans.
Ce sont des `TransitionKind.DISSOLVE` ordinaires : l’utilisateur peut les retailler
ou les supprimer. Les mouvements sont des `CameraAnimation` et
`CameraKeyframe` ordinaires, modifiables avec les outils existants.

## Zones et fidélité

Macro et Inspection ciblent les `Bounds` de deux objets de la scène. L’œuvre entière
reste toujours proposée, même sans analyse locale. Reveal se termine exactement sur
la pose entière `(x=0.5, y=0.5, zoom=1.0)` et aucune action 2D, 3D ou animation
générique n’est ajoutée automatiquement.

## Placeholders locaux

Le plan Réel est d’abord un clip de l’œuvre portant un marqueur d’interface explicite
`parameters.explore.role = real_placeholder`. Il demeure lisible et éditable, puis conserve son
identifiant lorsqu’un import local le remplace par un clip `STILL` ou `VIDEO`. Les
transitions restent ainsi éditables et le média n’est jamais copié.

La musique est représentée par une piste audio standard vide nommée
`Musique · à choisir`. L’import audio existant la remplit et la renomme `Musique`.
Il n’existe aucun état caché nécessaire au preview, à l’export ou à la réouverture du
projet.
