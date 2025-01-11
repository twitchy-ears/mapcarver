# mapcarver
Takes large images of maps, breaks them up into grids, and creates wiki pages one for each cell for RPG map note taking purposes

# Installation

Something like this, although feel free to do it in a more exciting way

```
pip install -r requirements.txt
```

This may also just work:

```
pipenv run ./mapcarver.py
```

# How to Configure / What it does

Check `example-dot-mapcarver.ini` and the `--help` option

Broadly you'll need to give it one argument of an image file, this is expected
to be a single large map file.

It will break this into cells (determined by the `--width` and `-height`) and
create a single main page on your wiki called "Map" that contains smaller
versions of all these cells joined together, then one page per-cell called
"Map X-n" (where X starts at A and goes towards Z and n starts at 1 and goes
towards 999).  Each of these sub-pages will be created according to the
template you give it and have a `{mapblock}` of data which centres the cell in
question and surrounds it with clickable greyscale images of its neighbouring
map cells.

# Gotchas

When updating the pages it builds them cell by cell, which means it often
includes a reference to an image that doesn't exist yet, which can lead to
broken images in your pages.

To fix this look at the `--wiki-just-purge` and `--wiki-purge` options.

# Updating just your pages

You can use `--wiki-skip-uploads` to just remake the pages, this enables you
to update templates across many pages.  Keep in mind that doing this will
remake the pages from scratch so you'll loose everything there.

