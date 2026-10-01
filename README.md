# Tracey

Traces alpha masks into Photoshop paths with [potracer](https://pypi.org/project/potracer/)
and embeds them into TIFFs.

```
uv run tracey                       # desktop UI
uv run potrace image.png -a 0.8     # command line
```

## UI

1. Drop an **alpha mask** (required) and, optionally, the **beauty render** (TIFF / PNG).
   Both fields take several files at once; masks and beauties are paired in name order.
   Files dropped anywhere on the window go to the mask field if their name contains
   `mask`, `alpha` or `matte`, otherwise to the beauty field.
2. Adjust the settings and click **Add to Queue**. Settings are stored with each job.
3. **Run Batch** traces every job that isn't done yet. Double-click a row to open its folder.

The mask's alpha channel is traced if it has one, its luminance otherwise. The path is saved
into the beauty render (or into the mask when there is none) as `<name>.tif`, scaled to fit if
the mask has a different resolution than the beauty.
