# Fidélité colorimétrique des œuvres en 3D

Le Studio sépare désormais la mise en lumière du décor de la restitution de l’œuvre.
Cette politique est appliquée par le même renderer pour l’aperçu, le rendu headless et
l’export final.

## Contrat persistant

Chaque plan `artwork_3d` accepte un objet `color_policy` :

```json
{
  "color_policy": {
    "mode": "faithful"
  }
}
```

Le projet compilé enregistre le contrat complet et versionné :

```json
{
  "schema_version": 1,
  "mode": "faithful",
  "texture_color_space": "srgb",
  "exposure": 1.0,
  "tone_mapping": "linear"
}
```

`faithful` est le mode par défaut. La texture sRGB est décodée par Qt, conservée à
exposition unitaire et rendue par un `PrincipledMaterial.NoLighting`. Les lampes colorées
continuent d’éclairer la pièce, le cadre et les accessoires, sans multiplier les pixels
de l’œuvre. Le mesh, la perspective, les déformations, le test de profondeur,
l’occlusion et les ombres portées restent actifs.

`scene_integrated` réactive `PrincipledMaterial.FragmentLighting`. Il est utile pour une
intégration volontaire de l’œuvre à l’ambiance lumineuse, mais il n’est jamais choisi
implicitement.

L’espace texture, l’exposition et le tone mapping sont volontairement verrouillés en
V3.1. Une recette qui tente d’introduire un filtre, une température arbitraire ou une
exposition différente échoue à la compilation au lieu de produire silencieusement une
nouvelle dominante.

## Contrôle qualité

Le module `artanimate.studio.color_fidelity` mesure l’écart CIEDE2000 entre une mire
source et son rendu, hors pixels de bord si demandé. Les seuils de livraison sont :

- médiane ΔE00 ≤ 2 ;
- percentile 95 ΔE00 ≤ 6.

Lorsqu’une recette avec un plan 3D demande une planche de contrôle, le job headless
ajoute une seconde planche `*-color-fidelity` : même œuvre, même frame et même caméra,
avec le rendu historiquement intégré à gauche et le rendu fidèle à droite. Son chemin,
son empreinte et l’état de validation artiste figurent dans `headless-report.json`.

La validation automatique ne remplace pas la validation de l’artiste : le rapport reste
à `artist_review: pending` jusqu’à cette revue visuelle.
