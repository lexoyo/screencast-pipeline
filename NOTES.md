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

## L'étape `short` reste à écrire — spec tirée d'un vrai aller-retour (31/08/2026)

Trois shorts ont été fabriqués **à la main** ce soir-là, dans un scratchpad, hors de ce
dépôt. Ils ont servi de banc d'essai ; ce qui suit est ce qu'il faut reporter ici. Alex :
« l'idée c'est pas que tu bricoles tout à la main ».

**L'étape doit rester hors de la séquence par défaut** (comme `plan` et `doctor`) : un
short se demande, il ne se produit pas à chaque tournage. Rien de ce qui suit ne doit
toucher aux neuf étapes qui rendent la vidéo longue.

### Ce qui a marché, à garder

- **Tailler dans le RUSH, pas dans le montage.** Le rush est en 2560x1440, `final.mp4` en
  1920x1080 : cadrer serré dans le second revient à zoomer une image déjà réduite. La
  conversion est simple tant qu'il n'y a pas de coupe : `rush = montage - durée des cartons
  insérés avant l'extrait`.
- **Bornes sur des frontières de cues**, jamais sur des secondes rondes — sinon ça coupe au
  milieu d'un mot, aux deux bouts.
- **Accélération ×1,15** (`setpts` + `atempo`), et le SRT re-timé du même facteur.
- **Pas de webcam.** L'écran gagne 240 px de haut, et le conflit entre les sous-titres et le
  cadre de la webcam disparaît. Le visage n'apporte rien à une démonstration d'interface.
- **Cadre calé en haut de l'écran** (`y = 0`) : le haut de l'interface doit rester visible,
  ce qui tombe hors cadre en bas n'a pas d'importance (décision d'Alex).
- **La webcam se calcule depuis la scène OBS**, jamais à l'œil : `~/.config/obs-studio/basic/
  scenes/<collection>.json`, item de la source V4L2 — `pos` est le CENTRE quand `align: 0`,
  `bounds` donne la boîte, à convertir vers la résolution de sortie.
- **Le renvoi pointe vers la page de doc**, pas vers l'hébergeur de la vidéo.

### Ce qui a échoué, et pourquoi — le cœur du sujet

**Le cadrage suivait l'activité (différence d'images) au lieu du curseur.** Les trois
remarques d'Alex sur les trois shorts viennent toutes de là : « le cadre part à gauche alors
que ma souris est à droite ». Ce qui bouge à l'écran (un canvas qui se rafraîchit) n'est pas
ce dont la voix parle. **C'est la position du curseur qu'il faut, pas l'activité.**

Deux pistes mesurées le même soir :

- **Gabarit + corrélation FFT** : trouve le curseur au pixel près en ~1,5 s en pleine
  résolution (bien moins en image réduite, et la précision n'a pas besoin d'être fine). Le
  score de corrélation est un garde-fou honnête : ~0,77 quand il trouve, <0,4 quand il se
  trompe. **C'est la voie à suivre.** Il faut extraire 3 ou 4 gabarits (flèche, main,
  barre de texte) une fois pour toutes.
- **Petit VLM local (moondream2)** : 60 s par image sur une machine sans GPU, et il décrit
  un screencast de l'éditeur comme « une visioconférence entre un homme et une femme ».
  Écarté, supprimé. Détails et chiffres : `knowledge/reference_moondream2_local_mesures.md`
  dans le workspace des agents.

**Où va la position du curseur** : dans `work/segments.json`, à côté du texte de chaque
segment — `{"i":12, "start":…, "text":"…", "cursor":{"x":…,"y":…,"confidence":…}}`. Le brain
du montage la lit et décide de la zone : le petit outil voit, le modèle comprend. Quand la
confiance est sous le seuil, écrire `null` plutôt qu'une position inventée.

### Deux zones à l'écran, une seule image verticale

Certains passages ont leur sujet **aux deux extrémités** : « le nom du calque n'est pas le
tag » montre les calques à gauche ET le champ `Tag name` à droite. Aucun cadre unique ne
raconte ça. La composition qui marche : deux vignettes empilées, séparées par un filet, la
zone gauche en haut et la zone droite en bas. L'étape doit donc supporter **une ou deux
vignettes par palier**, pas seulement un rectangle.

### Vérification — la règle qui a été enfreinte trois fois

**Une frame de contrôle par palier de cadrage**, pas une par short. Un cadre est fixe
pendant toute sa durée : une frame suffit à le juger, mais il en faut une pour *chaque*
cadre. Les trois défauts remontés par Alex étaient tous dans un palier que je n'avais pas
regardé.
