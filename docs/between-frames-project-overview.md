# Between Frames

**Turn the gallery into a continuous field of music.**

## The idea

Artworks create a distinctive atmosphere through their colors, textures, meanings, and relationships within a gallery. Between Frames translates this shared field into music, helping visitors experience the artworks more immersively.

Visitors listen through headphones. As they move, the music changes with their position. A handheld controller lets them express how the artworks make them feel and influence the sound.

## For curators

1. **Add an artwork:** upload an image and enter its title, artist, and optional context.
2. **Create a music prompt:** DeepSeek interprets both the artwork’s visual qualities and its meaning. The curator reviews and edits the result.
3. **Generate music:** Stability AI creates a recording from the approved prompt.
4. **Prepare a loop:** select a passage, blend its ending and beginning, name it, and save it to the music library.
5. **Connect two artworks:** select two saved loops and generate the music between them using inpainting.
6. **Preview the field:** listen to five musical states and choose a version for the gallery.

The curator decides which interpretations and musical connections feel right.

## Creating the music between artworks

Inpainting uses existing audio on both sides to generate a missing middle:

**A’s ending → generated music → B’s beginning**

We remove the two reference ends and keep only the newly generated interval. The curator can audition and trim this passage.

To create five states, we generate a shared middle C, then connect A to C and C to B:

**A → A–C connection → C → C–B connection → B**

The three interior recordings are prepared as loops. During playback, neighboring states blend as the visitor moves. Visitors can stop in the middle or walk back toward either artwork.

## For visitors

- **Move:** Bluetooth beacons near the artworks provide signals. A receiver moving with the visitor uses their relative signal strengths to estimate position.
- **Listen:** position determines the balance between the prepared musical states.
- **Express:** the controller accepts two emotional inputs:
  - **Valence:** how pleasant or unpleasant the feeling is.
  - **Intensity:** how strongly it is felt.

The intended interaction lets these inputs influence the music’s character and expression. Stronger feeling does not simply mean louder music.

## Essential technology

| Part | Role |
| --- | --- |
| LLM API   | Artwork image and context → editable music prompt |
| Stability AI | Generate recordings and inpaint connections |
| Python / FastAPI | Run tasks, process audio, and manage the library |
| SQLite and local files | Store artworks, recordings, and saved grids |
| BLE receiver | Estimate the visitor’s relative position |
| Handheld controller | Capture valence and intensity |
| Local audio engine | Loop, blend, and play music through headphones |

**Music is generated and curated before playback.** Movement controls local playback rather than making a new API request at every step.

## Prototype status

The curator platform, loop library, inpainting workflow, five-state player, and MP3 exports are implemented. A separate visitor-side prototype contains two-beacon positioning and GPIO emotion inputs. Connecting these into one experience, making controller input produce clear musical feedback, and testing it in the gallery are the next steps.
