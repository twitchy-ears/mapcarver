#!/usr/bin/python3

# pipenv run python mapcarver.py ~/big-map-file.png  --mode "wiki" --wiki-cell-template cell.template  --wiki-greyscale-images --wiki-main-page-resize 

import sys
import math
from datetime import datetime
import time
import tempfile
import shutil

import configargparse

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path, PurePath
import mwclient

# pipenv install ConfigArgParse
# pipenv install mwclient
# pipenv install Pillow

# use https://www.mediawiki.org/wiki/Extension:ImageMap in the mediawiki to create a single large image with overlayed text for each cell and the whole thing being a clickable link pile
#
# To think about adding a hex mode
# https://stackoverflow.com/questions/55385613/how-can-i-cut-custom-shape-from-an-image-with-pil
#
# The docs for mwclient
# https://mwclient.readthedocs.io/en/latest/user/page-ops.html

p = configargparse.ArgParser(default_config_files=['~/.mapcarver.ini'])
p.add('-c', '--config', is_config_file=True, help='config file path')
p.add('-d', '--debug', help='Debug mode', action='store_true')
p.add('--font-file', type=str, default='/usr/share/fonts/truetype/noto/NotoSansMono-Bold.ttf', help='Select TTF font to overlay coordinates')
p.add('--font-colour', type=str, default="red", help='Colour of font')
p.add('--font-size', type=int, default=28, help="Size of font")
p.add('--image-prefix', type=str, default="map-", help="Prefix of the image file names with this")
p.add('--height', type=int, default=256, help="Height of each square")
p.add('--width', type=int, default=256, help="Width of each square")

p.add('--wiki-site', type=str, help="Set the base for your mediawiki, expects just a raw host like wiki.domain.tld")
p.add('--wiki-scheme', type=str, default='https', help="http or https for connecting")
p.add('--wiki-path', type=str, default='/', help="path below the site to locate api.php use /w/ if you have a setup like wiki.domain.tld/w/api.php")
p.add('--wiki-user', type=str, help="Set username for editing the wiki")
p.add('--wiki-password', type=str, help="Set password for editing the wiki")
p.add('--wiki-main-map-page', type=str, default="Map", help="Name of main page to create the main map on, this will be overwritten")
p.add('--wiki-cell-prefix', type=str, default="map_", help="Prefix of the sub page to create for each cell, will have the cell name appended e.g. \"map_\" becomes \"map_a6\".  Each page will have its contents overwritten.  Be aware of _ because wiki treats it as a space")
p.add('--wiki-prepend', action="store_true", help="Will prepend content to wiki pages instead of overwriting them, which can be messy")
p.add('--wiki-image-overwrite', action="store_true", help="Will overwrite images on the wiki with fresh ones as they're generated")
p.add('--wiki-skip-uploads', action="store_true", help="Upload no images, just upload pages")
p.add('--wiki-cell-template', type=str, default=None, help="Template file for map cell subpages, just put {{mapblock}} in there where you want the images to appear")
p.add('--wiki-greyscale-images', action="store_true", default=False, help="Create greyscale images to upload to the wiki for the non-central images in the per-page map blocks")
p.add('--wiki-main-page-resize', action="store_true", default=True, help="Resize the map squares on the main page according to the resize value")
p.add('--wiki-main-page-resize-value', type=float, default=2.0, help="Resize the map blocks on the main map page to make them a bit smaller")
p.add('--wiki-api-sleep-retry', type=int, default=3, help="Seconds to sleep on API rate limiting")
p.add('--wiki-purge', action="store_true", default=False, help="After finishing the run wait a few seconds and then call a purge action on every page, this will flush the caches and make sure that images are uploaded (when images are uploaded after a page is finished then they tend to be rendered missing until the page cache expires)")
p.add('--wiki-just-purge', action="store_true", default=False, help="Do nothing else but purge the pages then exit")

p.add('--mode', default=['wiki'], choices=['wiki', 'html'], action='extend', type=str, nargs="+", help="Mode of output, options are wiki (output to specified wiki), 'html' (dump images to output-dir along with an index.html that displays them), or specify twice for both")
p.add("--output_dir", type=str, help="Directory for output, only needed for 'html' output mode")

p.add('--only', type=str, nargs="+", action='extend', default=[], help="Only process Cell X-N where X is an A-Z and N is a 1-99")

p.add("input_filename", type=str, help="Image for input")

options = p.parse_args()

def wiki_page_editor(page_name:str, new_text: str, reason = "mapcarver script"):
    "Takes a page name and the new text, if the --wiki-prepend argument was given it will prepend the text to any existing content, otherwise it'll overwrite it"
    page = site.pages[page_name]

    try: 
        if (options.wiki_prepend):
            original_text = page.text()
            page.edit(new_text + original_text, reason)
        else:
            page.edit(new_text, reason)

    except mwclient.errors.APIError as ex:
        if ex.code == 'ratelimited':
            print("API Rate Limited - sleep")
            time.sleep(options.wiki_api_sleep_retry)
            wiki_page_editor(page_name, new_text)

def file_entry_generator(row_id, col_id, imgtype = None):
    "Takes a row_id and col_id and combines them with an imgtype ['greyscale', 'resize'] to output a mediawiki [[File:whatever]] string"

    suffix = '.png'
    if (imgtype == 'greyscale'):
        suffix = "_greyscale.png"
    elif (imgtype == 'resize'):
        suffix = "_resize.png"

    cell_target = f"{options.image_prefix.title()}{row_id}-{col_id}{suffix}"
        
    return '[[File:' + f"{cell_target}|frameless|Map Cell {row_id}-{col_id}|link={options.wiki_cell_prefix}{row_id}-{col_id}" + ']]'


def image_uploader(filepath, filename, description):
    "Takes a filepath, the name you want it to be in the wiki (generally the last element of your path) and a description and uploads the image if required dealing with retries"

    if (options.wiki_skip_uploads):
        return filepath
    
    upload = False
    ignore_flag = False
    
    # Upload the file regardless
    if (options.wiki_image_overwrite):
        upload = True
        ignore_flag = True
        
    # Check for file and only upload if missing
    else:
        image_file = site.images[filename]
        if (not image_file.exists):
            upload = True

    # Actual upload
    if upload:
        print(f"Attempting site.upload({filepath}, {filename}, {description})")
        try: 
            site.upload(filepath, filename, description, ignore=ignore_flag)
            return filepath
        
        except mwclient.errors.APIError as ex:
            if ex.code == 'fileexists-no-change':
                print(f"File {filepath} already uploaded and identical, carrying on")
            if ex.code == 'ratelimited':
                print("API Rate Limited - sleep")
                time.sleep(options.wiki_api_sleep_retry)
                image_uploader(filepath, filename, description)
                
            else:
                print(f"Oops?  '{ex}'")

            return ex


    return "{filepath} didn't upload"



def purge_all_wiki_pages():
    "Runs through the wiki pages your image would generate and runs a purge/edit cycle on each to make sure they're refreshed, then does the main map page"
    for row in range(num_high):
        # Rows are A, B, C, etc
        row_id = chr(row + 65)
        for col in range(num_wide):
            col_id = col + 1
            
            cell_label = f"{row_id}-{col_id}"
            if (len(options.only) > 0 and cell_label not in options.only):
                continue
            
            cell_page_name = f"{options.wiki_cell_prefix}{row_id}-{col_id}"
            print(f"purging {cell_page_name}")
            page = site.pages[cell_page_name]
            contents = page.text(cache=False)
            page.purge()
            wiki_page_editor(cell_page_name, contents, "Fixing images")

            
            
    # And just purge the main page
    print(f"purging {options.wiki_main_map_page}")
    page = site.pages[options.wiki_main_map_page]
    contents = page.text(cache=False)
    page.purge()
    wiki_page_editor(options.wiki_main_map_page, contents, "Fixing images")


        

# For logs
ts_raw = datetime.now()
datestamp = ts_raw.strftime("%F")
timestamp = ts_raw.strftime("%F %H:%M:%S")


# test_page_name = 'Test Page'
# page = site.pages[test_page_name]
# if (page.exists):
#     text = page.text()
#     text += f"\n\nscript edited on {timestamp}"
#     page.edit(text, 'Updated by script')

#     # print(text)

#     print(page.text())
# else:
#     print(f"page '{test_page_name}' doesn't exist")


# # test log file
# log_page_name = f"mapcarver log {datestamp}"
# log_page = site.pages[log_page_name]
# text = log_page.text()
# if (len(text) > 0): 
#     text += f"\n\nwas run at {timestamp} and edited [[{test_page_name}]]"
# else:
#     text += f"Log Start\n\nwas run at {timestamp} and edited [[{test_page_name}]]"
    
# log_page.edit(text, 'logging activity')

# # Wrap images in <div style="white-space: nowrap;">
# #
# # https://mwclient.readthedocs.io/en/latest/user/files.html to upload

# exit(124)


# Check our font file
fontpath = options.font_file
try:
    Path(fontpath).is_file()
except FileNotFoundError:
    print(f"Font file '{fontpath}' doesn't exist, exiting")
    exit(1)
    
font_colour = options.font_colour

# Check the size options
square_width = options.height
square_height = options.width

resize_square_width = math.floor(square_width / options.wiki_main_page_resize_value)
resize_square_height = math.floor(square_height / options.wiki_main_page_resize_value)
        
if (square_width <= 0 or square_height <= 0):
    print(f"both --width ({square_width}) and --height ({square_height}) need to be > 0")
    exit(1)

text_x = square_width / 2
text_y = square_height / 2


# If we're outputting raw images/html then locate that
outpath = None
outfile_html = None
site = None
if ('html' in options.mode):
    try:
        rawpath = Path(options.output_dir)
        outpath = rawpath.expanduser()
        outpath = outpath.absolute()
    except FileNotFoundError:
        print(f"Path '{rawpath}' not found for output dir")
        exit(1)
        
    if outpath.is_dir is False:
        print(f"Path '{outpath}' is not a directory")
        exit(1)

    # Setup where we're putting outputs
    outfile_html = PurePath(outpath, 'index.html')



# Check we can get access to the wiki
if ('wiki' in options.mode):
    if (len(options.wiki_site) <= 0):
        print(f"Needs a --wiki-site setting on the command line or in the config file")
        exit(1)
            
    site = mwclient.Site(options.wiki_site, scheme = options.wiki_scheme, path = options.wiki_path)
    site.login(username = options.wiki_user, password = options.wiki_password)
    # print(site)

    cell_template = '{{mapblock}}'
    if (options.wiki_cell_template is not None):
        try:
            rawpath = Path(options.wiki_cell_template)
            cell_path = rawpath.expanduser()
            cell_path = cell_path.absolute()
        except FileNotFoundError:
            print(f"--wiki-cell-template '{options.wiki_cell_template}' not found")
            exit(1)

        with open(cell_path, 'r') as file:
            cell_template = file.read()

    

# Get a temp directory to store work in:
tmpdir_obj = tempfile.TemporaryDirectory()
tmpdir = tmpdir_obj.name
# tmpdir = '/tmp/mapcarver'


    
# Locate the actual main input file
try: 
    rawpath = Path(options.input_filename)
    fullpath = rawpath.expanduser()
    fullpath = fullpath.absolute()
except FileNotFoundError:
    print(f"Path '{rawpath}' not found for input file")
    exit(1)

# Open our main image file
img = Image.open(fullpath)

# Work out how big it is
num_wide = math.ceil(img.width / square_width)
num_high = math.ceil(img.height / square_height)

# Output some debugging
print(f"{fullpath}: {img}, {square_width}px / {square_height}px boxes = {num_wide} wide / {num_high} high boxes, resized to {resize_square_width}px / {resize_square_height}px")

print(f"Operating with tmpdir '{tmpdir}'")

if ('html' in options.mode): 
    print(f"Going into {outpath}")
    print(f"Index in '{outfile_html}'")

if ('wiki' in options.mode):
    print(f"Going into '{options.wiki_site}' as '{options.wiki_user}': {site}")

# Start the index file
if ('html' in options.mode):
    out_f = open(outfile_html, "w")
    out_f.write(f"<html><head><title>{fullpath}</title></head><body><div style=\"white-space: nowrap;\">\r\n")

# Start the main map page
if ('wiki' in options.mode):
    mmp_text = '<div style="white-space: nowrap; overflow-x: auto; overflow-y: hidden;">\n'

# If we're just purging do that and quit
if ('wiki' in options.mode and options.wiki_just_purge is True):
  print("Purging all pages")
  purge_all_wiki_pages()
  exit(0)
    
    
# Process the image
for row in range(num_high):


    # Calculate top and bottom of the row
    top_line = 0 + (square_height * row)
    bottom_line = top_line + square_height
    if row == (num_high - 1):
        bottom_line = img.height

    # Rows are A, B, C, etc
    row_id = chr(row + 65)
        
    # print(f"Row: {row}: start: {top_line}, end: {bottom_line}")

    # Process the columns
    for col in range(num_wide):
        left_line = 0 + (square_width * col)
        right_line = left_line + square_width
        if col == (num_wide - 1):
            right_line = img.width

        # Columns are 1, 2, 3, etc
        col_id = col + 1

        cell_label = f"{row_id}-{col_id}"
        if (len(options.only) > 0 and cell_label not in options.only):
            # print(f"Skipping '{cell_label}'")
            continue

        print(f"{row_id}-{col_id} ({row}/{col}):start: {top_line}, end: {bottom_line}, left: {left_line}, right: {right_line}")

        # Work out where the image is going
        outfile = options.image_prefix + str(row_id) + '-' + str(col_id) + '.png'
        outfile_path = PurePath(tmpdir, outfile)
        print(outfile_path)

        # Actually chop it out of the image and save to the disk
        box = (left_line, top_line, right_line, bottom_line)
        region = img.crop(box)

        # Add text overlay
        font = ImageFont.truetype(fontpath, options.font_size)
        d = ImageDraw.Draw(region)
        d.text((text_x, text_y), f"{row_id}{col_id}", fill=font_colour, anchor="ms", font=font)
        
        print(region)
        region.save(str(outfile_path), "PNG")

        greyscale_image = region.convert("LA")
        greyscale_outfile = options.image_prefix + str(row_id) + '-' + str(col_id) + '_greyscale.png'
        greyscale_path = PurePath(tmpdir, greyscale_outfile)
        greyscale_image.save(str(greyscale_path), "PNG")

        resize_image = region.resize((resize_square_width, resize_square_height))
        resize_outfile = options.image_prefix + str(row_id) + '-' + str(col_id) + '_resize.png'
        resize_path = PurePath(tmpdir, resize_outfile)
        resize_image.save(str(resize_path), "PNG")



        # For HTML mode write into index and copy to output dir
        if ('html' in options.mode):
            out_f.write(f"<img src=\"{outfile}\" />\r\n")
            
            if (col == (num_wide - 1)):
                out_f.write("<br />\r\n")

            shutil.copy2(outfile_path, outpath)


        # For wiki mode write into the index, the page in question, and upload the file
        if ('wiki' in options.mode):

            image_uploader(outfile_path, outfile, f"Map cell {row_id}-{col_id}")
            if (options.wiki_greyscale_images):
                image_uploader(greyscale_path, greyscale_outfile, f"Map Cell (Greyscale) {row_id}-{col_id}")
                   
            if (options.wiki_main_page_resize):
                image_uploader(resize_path, resize_outfile, f"Map Cell (Resized) {row_id}-{col_id}")
                
            cell_page_name = f"{options.wiki_cell_prefix}{row_id}-{col_id}"
            mapblock_data = '<div style="white-space: nowrap; overflow-x: auto; overflow-y: auto">\n'

            surround_image_type = None
            main_image_type = None
            if (options.wiki_greyscale_images):
                surround_image_type = 'greyscale'
            if (options.wiki_main_page_resize):
                main_image_type = 'resize'
            
            # Add above line
            if (row > 0):
                prev_row = chr((row - 1) + 65)

                # Avoid looping from A back to Z
                if (col > 0):
                    mapblock_data += file_entry_generator(prev_row, col_id - 1, imgtype = surround_image_type)

                mapblock_data += file_entry_generator(prev_row, col_id, imgtype = surround_image_type)

                # Over overshooting
                if (col < (num_wide - 1)):
                    mapblock_data += file_entry_generator(prev_row, col_id + 1, imgtype = surround_image_type)

                mapblock_data += "<br />"

            # Add left
            if (col > 0):
                mapblock_data += file_entry_generator(row_id, col_id - 1, imgtype = surround_image_type)

            # Add current to both the mapblock and the main map page
            mapblock_data += file_entry_generator(row_id, col_id)
            mmp_text += file_entry_generator(row_id, col_id, imgtype = main_image_type)
            if (col == num_wide - 1):
                mmp_text += "<br />"

            # Add right
            if (col < (num_wide - 1)):
                mapblock_data += file_entry_generator(row_id, col_id + 1, imgtype = surround_image_type)

            mapblock_data += "<br />"

            # Add below line
            if (row < num_high):
                next_row = chr((row + 1) + 65)
                if (col > 0):
                    mapblock_data += file_entry_generator(next_row, col_id - 1, imgtype = surround_image_type)

                mapblock_data += file_entry_generator(next_row, col_id, imgtype = surround_image_type)

                if (col < (num_wide - 1)):
                    mapblock_data += file_entry_generator(next_row, col_id + 1, imgtype = surround_image_type)
            

            # And end
            mapblock_data += "</div>\n"

            cell_page_contents = cell_template.format(mapblock=mapblock_data)
            print(f"Creating page '{cell_page_name}'")
            wiki_page_editor(cell_page_name, cell_page_contents)
            
        
# Tail the html index
if ('html' in options.mode): 
    out_f.write("</div></body></html>")
    out_f.close()

    print(f"closed {out_f}")


# Write the main map page
if ('wiki' in options.mode and len(options.only) == 0):
    mmp_text += '</div>'
    wiki_page_editor(options.wiki_main_map_page, mmp_text)


if ('wiki' in options.mode and options.wiki_purge is True):
  print("Sleeping before purge")
  time.sleep(options.wiki_api_sleep_retry)
  purge_all_wiki_pages()



      
# All good.
tmpdir_obj.cleanup()
exit(0)
