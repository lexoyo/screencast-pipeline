# Journal des tournages — ce qu'on observe, sans y toucher tout de suite

Ce fichier ne décrit pas le code : il note ce qu'un rendu a donné en vrai, épisode par
épisode. Un défaut vu une fois est une anecdote, vu trois fois c'est un correctif à faire.
Rien n'est modifié sur la foi d'une seule occurrence.

## 2026-08-24 — screencast Goose (`2026-08-24_17-27-43_montage`)

Cerveau : `openrouter/anthropic/claude-sonnet-5`, variant `medium`, via opencode.
Verdict d'ensemble d'Alex : **ça a bien marché**. Deux réserves.

### 1. Le son de l'intro

Enchaînement entendu : **a capella, puis un blanc, puis un tout petit peu de musique,
coupée net**. Ce n'est pas une décision du modèle — l'EDL ne porte que les coupes et les
plans. C'est le carton d'intro : la piste chantée, le silence entre les deux, et la
musique de `sonorita` qui rentre trop tard puis se fait trancher par la fin du carton.
À regarder du côté du montage du bookend (durée du carton, offset et fondu de la musique,
alignement du jingle), pas du côté du modèle.

### 2. La fin de l'installation a été coupée

Ça, en revanche, c'est bien une décision du cerveau : un `drop` sur la fin d'un passage
qu'Alex voulait garder. Deux causes possibles, à départager avant de conclure :

- **le modèle** — il a jugé la fin de séquence sans intérêt ;
- **le prompt** — `montage.md` autorise `fumble` à couvrir « des dizaines de secondes »
  quand le locuteur patauge, et demande de couper les fins de phrase abandonnées. Une
  installation qui se termine dans un moment d'hésitation coche les deux cases.

Si le défaut se reproduit avec un autre modèle, c'est le prompt qu'il faut reprendre, pas
le modèle. La trace de l'appel (`brain-log/`) garde le `reason` retenu pour ce span : c'est
lui qui tranchera.

## 2026-08-24 — même rush, cerveau `openrouter/moonshotai/kimi-k2.5`

EDL sans défaut mécanique : couverture 0 → 881,9 s complète, aucun trou, 13 plans dont 4
coupés (18 s retirés). Titre et chapitres corrects, dix outils cités.

Deux remarques d'Alex, et la seconde est la plus instructive de la journée.

### 1. Aucun carton, ni au début ni à la fin — donc pas de musique

Alex constate à l'écran : pas de musique sur l'intro, **et pas de slide de fin non plus**.
L'EDL explique les deux : `intro`, `outro` et `jingle` sont **absents** tous les trois.
La vidéo démarre donc sur la première phrase et s'arrête sur la dernière, sans habillage. Le prompt autorise à
omettre un carton « quand la prise ne le mérite pas », et Kimi a choisi de tout omettre —
pas de carton, donc pas de jingle, donc pas de musique. Sonnet, lui, avait produit les
trois. C'est une divergence de jugement entre modèles sur une consigne facultative, pas
un bug : si ces cartons ne sont pas facultatifs en pratique, c'est au prompt de le dire.

### 2. La fin de l'installation coupée — DEUX modèles sur deux

Sonnet l'avait fait, Kimi le refait : `fumble` sur **240,5 → 250,5 s**, dix secondes. Deux
modèles indépendants qui coupent le même passage, ce n'est plus le modèle : c'est le
prompt. La règle `fumble` de `montage.md` autorise explicitement à supprimer « des
dizaines de secondes » quand le locuteur patauge, et une installation qui se termine dans
un moment d'hésitation coche la case.

Alex : « ça doit être ma faute ». Peut-être, mais la conséquence est la même — une fin de
séquence utile disparaît. Deux pistes le jour où on y touche : durcir la règle `fumble`
(interdire de couper la FIN d'une séquence technique, où se trouve le résultat), ou
plafonner la durée d'un `fumble`. Ne rien changer avant d'avoir vu un troisième rush.

### Coût comparé, même rush, étape de montage seule

| Modèle | Coût | Verdict mécanique |
|---|---|---|
| claude-sonnet-5 | 0,48 € | ✓ |
| claude-sonnet-5 `[medium]` | 0,35 € | ✓ |
| z-ai/glm-5.2 | 0,32 € | ✗ (1 appel en agent, 1 figé sans réponse) |
| inkling-small | 0,09 € | ✗ timeline amputée et non monotone |
| **kimi-k2.5** | **0,07 €** | **✓** |

Kimi-k2.5 fait le travail pour un septième du prix de Sonnet. Le variant `medium` de
Sonnet n'a rien apporté de visible pour 0,35 €.
