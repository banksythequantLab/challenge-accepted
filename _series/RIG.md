# The rig — capture, naming, publishing

Decided once so episode 12 is not a rescue job.

---

## 1 · Capture

**Screen.** 1920×1080, 30fps. Match the demo video so cut-ins between the two never
letterbox. Browser at 100% zoom, bookmarks bar hidden, single tab, Focus Assist on.

**Do not film a maximised browser with your whole desktop behind it.** Either
full-screen the browser (F11) or capture the window only. Chrome's tab strip in a
YouTube thumbnail reads as amateur; a clean viewport does not.

**Audio.** Record voice to a separate track. Every fix in the demo video was possible
because the narration was separable from the picture — keep that property. If OBS,
that is a second audio track on the recording, not just the mix.

**Levels.** Speak, look at the meter, leave headroom. Clipped narration cannot be
repaired and will cost you a re-shoot.

**Length.** Under 12 minutes for a task episode. The demo is 3:01 and that is the
ceiling for anything a stranger watches cold; a subscriber will give you longer.

---

## 2 · Naming

One scheme, applied from episode 1, sortable forever:

```
_series/ep01/                       ep<NN>, zero-padded
  raw/       ep01_screen.mkv        recorder output, never edited in place
             ep01_voice.wav
  cut/       ep01_v1.mp4            renders, versioned
  shots/     ep01_thumb.png         stills and thumbnails
  ep01.md                           the beat sheet
  ep01_state.json                   tracker.py output AT FILM TIME
```

**`ep01_state.json` is the important one.** Copy `_series/progress.json` into the
episode folder before each shoot. Six weeks from now, "what was true when I said
that?" has an answer instead of an argument. It is also what lets you put an honest
progress bar in the next episode.

MKV for capture, not MP4 — a crashed recorder loses an MP4 entirely and leaves an MKV
playable.

---

## 3 · Titles and descriptions

**Title.** Concrete noun, real number, no hype. The number carries it.

- ✅ `Day 0: the AI told me I need 25 signed clients in 90 days`
- ✅ `I have 34 domains. It told me 5 of them matter.`
- ❌ `AI Agents Build My $25K Business?! (INSANE)`

**Description template** — first two lines are what shows above the fold:

```
Day <N> of building to $25,000/month in 90 days from rank-and-rent sites.
Started at $0, a $1,500 budget and 34 domains. <ONE-LINE OUTCOME OF THIS EPISODE>

State at the top of this episode:
  <X> of 15 micro-goals complete
  <Y> with a working tool built and tested
  $<Z>/month earned so far

The goal graph and every tool in it were built by Challenge Accepted, nine agents
running on Google Cloud. It is live and free to try:
  https://challengeaccepted.app
  https://github.com/banksythequantLab/challenge-accepted

This episode's task: <NODE TITLE>  (<node-id>)
The tool it built for it: <TOOL NAME>

00:00 <chapter>
...
```

**Fill the state block from `ep01_state.json`, not from memory.** If earned is still
$0 in episode 9, it says $0 in episode 9. The series is only worth anything if that
number is trustworthy when it finally moves.

---

## 4 · Thumbnails

`python _series\thumbs.py` renders 1280×720 thumbnails in the docket's visual
language — dark ground, safety orange, one number carrying the frame.

Edit the `EPISODES` list at the top of that file and re-run. One big number, three
words, episode chip. Text stays inside the middle 80% so YouTube's duration badge
never lands on a word.

---

## 5 · Per-episode loop

1. `python _series\tracker.py` → confirm the numbers you are about to say
2. Copy `progress.json` → `_series/epNN/epNN_state.json`
3. Film. Screen and voice on separate tracks.
4. Cut. Burn captions — same reason as the demo video: half your audience watches muted.
5. `python _series\thumbs.py` for the card
6. Publish **Public**, fill the state block from the JSON, not from memory
7. Re-run `tracker.py` after any real progress so the docket page stays true
