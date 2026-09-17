# Teaching material tags

This folder holds **links and concept tags only**, never lecture media, slides, transcripts or slide text. Those stay in `data/raw/` (gitignored), because course material is usually licensed (for example CC BY-NC-SA) and must not be rehosted.

```
materials/
  sources/<source_id>.json     # where the material lives, its licence and attribution
  <source_id>.tags.json        # timestamps, slide numbers and concept tags (reviewable)
data/raw/                      # local only
  <source_id>/                 # the downloaded video and slide PDF
  processed/<source_id>/       # transcript.json, chunks.json, slides.json
  processed/thumbnails/<source_id>/slide-NNN.png
```

## Building a tag file

```bash
uv sync --extra materials      # faster-whisper, only needed for transcription
uv run labassistant-materials build materials/sources/mit6_0001_f16_lec6.json \
    --media data/raw/mit6_0001_f16_lec6/lecture6.mp4 \
    --slides data/raw/mit6_0001_f16_lec6/lecture6_slides.pdf
```

1. The lecture is transcribed locally with faster-whisper (cached in `transcript.json`).
2. The transcript is grouped into 30–90 second chunks, breaking at pauses and sentence ends.
3. Slide text and PNG thumbnails are extracted with PyMuPDF.
4. The configured LLM tags each chunk and slide with concept ids from `knowledge/recursion.json`, in batches.
5. The tag file is written. Entries already marked `"reviewed": true` are never overwritten.

## Reviewing tags (please do this)

```bash
uv run labassistant-materials review mit6_0001_f16_lec6
```

This prints each chunk and slide with its tags next to the local text. Edit `materials/<source_id>.tags.json` by hand:

- fix `concept_ids` (use ids from the concept graph; an empty list means "teaches none of them");
- set `"reviewed": true` on every entry you have checked.

Run `review` again: it reports unknown concept ids and other problems. Reviewed entries are ranked above unreviewed ones in retrieval.

## Tag file format

```json
{
  "source": { "id": "...", "title": "...", "page_url": "...",
              "timestamp_url_template": "https://...#t={seconds}",
              "slides_url": "...", "license": "...", "attribution": "..." },
  "chunks": [
    { "id": "mit6_0001_f16_lec6-c012", "start": 612.4, "end": 671.9,
      "concept_ids": ["base_case", "recursive_case"], "reviewed": false }
  ],
  "slides": [
    { "number": 10, "concept_ids": ["base_case"], "reviewed": false }
  ]
}
```

- `start` / `end` are seconds from the start of the recording.
- `number` is the 1-based slide (PDF page) number.

## Retrieval

```bash
uv run labassistant-materials retrieve base_case
```

For a concept, retrieval picks the tagged chunk and slide that are reviewed, most focused (fewest other concepts) and earliest. See `src/labassistant/materials/retrieval.py`.
