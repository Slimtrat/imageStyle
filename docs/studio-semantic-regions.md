# Régions sémantiques du Studio

Une région sémantique désigne un élément de l’œuvre dans son espace canonique : un
œil, une bouche, un personnage, une fleur ou une forme libre. Elle ne dépend ni du
moteur qui l’a proposée, ni du plan sur lequel elle sera animée.

## Contrat de produit

Une région persistée contient toujours :

- un identifiant et un type sémantique ;
- un cadrage normalisé dans l’œuvre source ;
- un masque canonique portable ;
- des affordances, par exemple `blinkable` ;
- la provenance de l’analyse et sa version ;
- les informations nécessaires pour la corriger manuellement.

Les animations consomment uniquement ce contrat. Le blink, la sortie de cadre ou une
future déformation ne doivent donc jamais appeler directement un détecteur.

## Stratégie de détection

Le chemin recommandé est hybride :

1. des primitives locales déterministes proposent rapidement des composantes à partir
   des contours, contrastes, couleurs et régions connexes ;
2. un analyseur sémantique local optionnel attribue des catégories et affine les
   masques lorsque l’image est figurative ;
3. l’utilisateur confirme, renomme ou corrige les propositions ;
4. le Studio fige le résultat en masque canonique portable dans le projet.

Cette séparation répond à deux réalités des œuvres : un contour très net n’est pas
forcément un objet, et un objet peint peut traverser plusieurs aplats sans contour
fermé. Aucun moteur unique ne doit être considéré comme vérité.

Le port Python `SemanticRegionDetector` accepte l’image canonique et retourne des
`SemanticRegionCandidate` neutres. Plusieurs implémentations pourront être comparées
avec les mêmes critères sans modifier les recettes ou le compositeur :

- fidélité du masque aux bords peints ;
- stabilité sur œuvres abstraites et figuratives ;
- coût mémoire et temps d’analyse hors ligne ;
- reproductibilité et poids dans l’EXE ;
- possibilité de proposer plusieurs candidats plutôt que d’imposer un résultat.

## Slice actuelle

La V3 accepte une région manuelle fiable dans `semantic_regions`, génère ou importe son
masque, enregistre la provenance `manual.recipe-regions`, puis reprojette ce même masque
sur la photo réelle avec l’homographie du raccord spatial. `region.blink` peut ainsi
s’exécuter à la fin du plan réel tout en suivant son animation de caméra.

Pour une région œil, le contrat conserve aussi une géométrie de paupière indépendante
du timing de l’action : axe local, courbure, amplitude, zone de protection de la matière
et largeur du trait fermé. Le renderer prélève la couleur dominante du visage, conserve
sa microtexture et déplace deux fronts de paupière vers l’axe. Il ne rebouche plus l’œil
par inpainting et ne réduit plus sa texture en bande. Une planche headless 2×4 compare
automatiquement les quatre états dans l’œuvre canonique et dans la photo réelle.

La détection automatique reste une capacité d’analyse séparée. Elle alimentera le même
contrat et ne changera ni la sauvegarde du projet, ni les actions existantes.
