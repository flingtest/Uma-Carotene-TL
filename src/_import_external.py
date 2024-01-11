import requests
import util
from multiprocessing.pool import Pool
import os
import glob
import json
import datetime
from selenium import webdriver
import time

MISSIONS_JSONS = [
    "66",
    "67",
]

def fetch_chara_data(chara_id):
    out = (chara_id, {})
    r = requests.get(f"https://umapyoi.net/api/v1/character/{chara_id}")

    if not r.ok:
        return out
    
    convert_map = {
        "profile": 163,
        "slogan": 144,
        "ears_fact": 166,
        "tail_fact": 167,
        "strengths": 164,
        "weaknesses": 165,
        "family_fact": 169
    }

    data = r.json()

    for key, category in convert_map.items():
        if data.get(key):
            out[1][category] = data[key]
    
    return out

def import_category(category, data):
    print(f"Importing text category {category}")

    json_path = util.MDB_FOLDER_EDITING + f"text_data/{category}.json"

    if not os.path.exists(json_path):
        print(f"Skipping {category}, file not found. Run _update_local.py first.")
        return

    json_data = util.load_json(json_path)

    for chara_id, value in data:
        key = f"[{category}, {chara_id}]"
        for entry in json_data:
            if key in entry["keys"]:
                entry["text"] = value.strip()
                entry['new'] = False
                break
        else:
            print(f"WARN: Couldn't find {key} in {category}.json")
    
    util.save_json(json_path, json_data)


def apply_umapyoi_character_profiles(chara_ids):
    # Fetch all character data
    print("Fetching character data")
    with Pool(5) as pool:
        chara_data = pool.map(fetch_chara_data, chara_ids)

    # Filter out characters with no data
    chara_data = [chara for chara in chara_data if chara[1]]

    # Convert to category data
    category_data = {}
    for chara in chara_data:
        for category, value in chara[1].items():
            tup = (chara[0], value)
            if category in category_data:
                category_data[category].append(tup)
            else:
                category_data[category] = [tup]
    
    # Update intermediate data per category
    for category, data in category_data.items():
        import_category(category, data)


def fetch_outfits(chara_id):
    out = []
    r = requests.get(f"https://umapyoi.net/api/v1/outfit/character/{chara_id}")
    
    if not r.ok:
        return out
    
    if r.status_code == 204:
        # No outfits
        return out
    
    data = r.json()

    for outfit in data:
        out.append((outfit['id'], outfit['title_en']))
    
    return out



def apply_umapyoi_outfits(chara_ids):
    # Fetch outfits
    outfit_data = []

    for chara_id in chara_ids:
        outfit_data.append(fetch_outfits(chara_id))
    
    proper_outfit_list = []
    for outfit_list in outfit_data:
        if not outfit_list:
            continue
        for outfit in outfit_list:
            proper_outfit_list.append(outfit)
    
    # Update intermediate data
    import_category(5, proper_outfit_list)



def get_umapyoi_chara_ids():
    # Fetch all character IDs

    r = requests.get("https://umapyoi.net/api/v1/character")
    r.raise_for_status()

    data = r.json()

    chara_ids = [chara["game_id"] for chara in data if chara.get("game_id")]

    return chara_ids


def fetch_story_json(url):
    r = requests.get(url)
    r.raise_for_status()

    return r.json()


def import_external_story(local_path, url_to_github_jsons):
    # Download all jsons from github
    print("Downloading jsons from github")

    r = requests.get(url_to_github_jsons)
    r.raise_for_status()

    urls = [data['download_url'] for data in r.json()]


    with Pool(5) as pool:
        story_data = pool.map(fetch_story_json, urls)
    
    # imported_stories = {data['bundle']: data for data in story_data}
    imported_stories = {}
    imported_titles = {}
    for data in story_data:
        cur_blocks = {}
        for block in data['text']:
            cur_blocks[block['pathId']] = {
                'path_id': block['pathId'],
                'block_id': block['blockIdx'],
                'text': block['enText'],
                'name': block['enName'],
                'clip_length': block.get('newClipLength', block['origClipLength']),
                'source_clip_length': block['origClipLength'],
            }

            anim_data = block.get('animData')
            choices = block.get('choices')

            if anim_data:
                cur_data = []
                for anim in anim_data:
                    cur_data.append({
                        'orig_length': anim['origLen'],
                        'path_id': anim['pathId'],
                    })
                cur_blocks[block['pathId']]['anim_data'] = cur_data
            
            if choices:
                cur_data = []
                for choice in choices:
                    cur_data.append({
                        'text': choice['enText']
                    })
                cur_blocks[block['pathId']]['_choices'] = cur_data
                # cur_blocks[block['pathId']]['choices'] = choices
        
        imported_stories[data['bundle']] = cur_blocks
        imported_titles[data['bundle']] = data['title']

    print(imported_stories.keys())

    # Load local story data
    print("Loading local story data")
    local_files = glob.glob(os.path.join(util.ASSETS_FOLDER_EDITING, local_path) + "/*.json")

    for local_file in local_files:
        data = util.load_json(local_file)

        file_name = os.path.basename(local_file)
        
        if not data['hash'] in imported_stories:
            print(f"Skipping {file_name}, not found in github")
            continue

        print(f"Merging {file_name}")

        if data['hash'] in imported_titles:
            data['title'] = imported_titles[data['hash']]
        
        for block in data['data']:
            import_block = imported_stories[data['hash']].get(block['path_id'])

            if not import_block:
                print(f"Skipping {block['path_id']}, not found in github")
                continue

            block.update(import_block)

            # Fix choices
            if block.get('_choices'):
                for i, choice in enumerate(block['_choices']):
                    block['choices'][i]['text'] = choice['text']
                
                del block['_choices']

        util.save_json(local_file, data)
    
    print("Done")


def apply_gametora_skills():
    print("Importing GameTora skills")

    r = requests.get("https://gametora.com/loc/umamusume/skills.json")
    r.raise_for_status()

    gt_data = r.json()

    gt_name_dict = {data['name_ja']: data['name_en'] for data in gt_data if data.get('name_en')}
    gt_desc_dict = {data['id']: data['desc_en'] for data in gt_data if data.get('desc_en')}

    # Load local skill data
    print("Skill names")

    prefix = os.path.join(util.MDB_FOLDER_EDITING, "text_data")
    name_files = [
        "47",
        "147"
    ]

    for name_file in name_files:
        data = util.load_json(os.path.join(prefix, f"{name_file}.json"))

        for entry in data:
            if entry['source'] in gt_name_dict:
                entry['prev_text'] = entry['text']
                entry['text'] = gt_name_dict[entry['source']]
                entry['new'] = False

        util.save_json(os.path.join(prefix, f"{name_file}.json"), data)

    print("Skill descriptions")
    desc_data = util.load_json(os.path.join(prefix, "48.json"))

    for entry in desc_data:
        keys = json.loads(entry['keys'])
        skill_id = keys[0][1]
        if skill_id in gt_desc_dict:
            cur_desc = gt_desc_dict[skill_id]
            cur_desc = util.add_period(cur_desc)
            entry['prev_text'] = entry['text']
            entry['text'] = cur_desc
            entry['new'] = False
    
    util.save_json(os.path.join(prefix, "48.json"), desc_data)

    print("Done")


def fetch_skill_translations():
    path = os.path.join(util.MDB_FOLDER_EDITING, "text_data", "47.json")
    data = util.load_json(path)
    tl_dict = {}
    for entry in data:
        tl_dict[entry['source']] = entry['text']

    return tl_dict


def scrape_missions():
    driver = webdriver.Firefox()

    # Get story event URLs
    driver.get("https://gametora.com/umamusume/events/story-events")
    while not driver.execute_script("""return document.querySelector("[class^='utils_umamusume_']");""") and time.perf_counter() - t0 < 6:
        time.sleep(1.0)
    time.sleep(1.0)
    
    urls = driver.execute_script(
"""
let out = [];
let ele = document.querySelector("[class^='utils_umamusume_']");
let elements = ele.querySelectorAll("a");
for (let i = 0; i < elements.length; i++) {
    out.push(elements[i].href);
}
return out;
""")
    
    urls = set(urls)
    urls = list(urls)

    current_year = datetime.datetime.now().year
    start_year = 2021
    urls += [
        "daily",
        "main",
        "permanent"
    ]
    urls += [f"history-{year}" for year in range(start_year, current_year + 1)]

    out_dict = {}

    for url in set(urls):
        if not url.startswith("http"):
            url = f"https://gametora.com/umamusume/missions/{url}"

        driver.get(url)

        t0 = time.perf_counter()
        while not driver.execute_script("""return document.querySelector("[class^='missions_row_text_']");""") and time.perf_counter() - t0 < 6:
            time.sleep(1.0)
        time.sleep(2.0)
        ele = driver.execute_script("""
            let skill_dict = arguments[0];
            let out = [];
            let elements = document.querySelectorAll("[class^='missions_row_text_']");
            for (let i = 0; i < elements.length; i++) {
                if (elements[i].children.length != 2) {
                    continue;
                }
                let jp = elements[i].children[0].innerText;
                let en_element = elements[i].children[1];
                let skill_elements = en_element.querySelectorAll("[aria-expanded='false']");
                for (let j = 0; j < skill_elements.length; j++) {
                    let skill_name = skill_elements[j].innerText;
                    if (skill_dict.hasOwnProperty(skill_name)) {
                        skill_elements[j].textContent = skill_dict[skill_name];
                    }
                }
                let en = en_element.innerText;
                out.push([jp, en]);
            }
            return out;
        """, fetch_skill_translations())

        for e in ele:
            out_dict[e[0]] = e[1]
    
    driver.close()

    return out_dict

def scrape_title_missions():
    driver = webdriver.Firefox()

    driver.get("https://gametora.com/umamusume/trainer-titles")

    t0 = time.perf_counter()
    while not driver.execute_script("""return document.querySelector("[class^='titles_table_row_']");""") and time.perf_counter() - t0 < 6:
        time.sleep(1.0)
    time.sleep(1.0)

    data = driver.execute_script(
"""
let skill_dict = arguments[0];
let out = {};
let elements = document.querySelectorAll("[class^='titles_table_row_']");
for (let i = 0; i < elements.length; i++) {
    let src = elements[i].querySelector("img").src;
    let segments = src.split("_");
    let id = segments[segments.length - 1].split(".")[0];

    // Replace skill names
    let descr_element = elements[i].querySelector("[class^='titles_table_desc_']");
    let skill_elements = descr_element.querySelectorAll("[aria-expanded='false']");
    for (let j = 0; j < skill_elements.length; j++) {
        let skill_name = skill_elements[j].innerText;
        if (skill_dict.hasOwnProperty(skill_name)) {
            skill_elements[j].textContent = skill_dict[skill_name];
        }
    }

    let descr = descr_element.innerText;
    out[id] = descr;
}
return out;
""", fetch_skill_translations())
    return data

def apply_gametora_missions():
    print("Importing GameTora missions")

    mission_data = scrape_missions()

    if not mission_data:
        print("Failed to scrape missions")
        return

    # Load local mission data
    for json_file in MISSIONS_JSONS:
        path = os.path.join(util.MDB_FOLDER_EDITING, "text_data", f"{json_file}.json")
        data = util.load_json(path)

        for entry in data:
            source = entry['source'].replace("\n", "").replace("\\n", "")
            if source in mission_data:
                entry['prev_text'] = entry['text']
                entry['text'] = util.add_period(mission_data[source])
                entry['new'] = False

        util.save_json(path, data)

    print("Done")

def apply_gametora_title_missions():
    print("Importing GameTora title missions")

    # {ID: EN}
    mission_data = scrape_title_missions()

    if not mission_data:
        print("Failed to scrape missions")
        return
    

    with util.MDBConnection() as (conn, cursor):
        new_dict = {}
        for key in mission_data:
            cursor.execute(
                """
                SELECT id FROM mission_data WHERE item_id = ?;
                """,
                (key,)
            )
            rows = cursor.fetchall()
            if not rows:
                continue
            for row in rows:
                new_id = str(row[0])
                if new_id.startswith("20"):
                    continue
                new_dict[new_id] = mission_data[key]
        mission_data.update(new_dict)


    # Load local mission data
    for json_file in MISSIONS_JSONS:
        path = os.path.join(util.MDB_FOLDER_EDITING, "text_data", f"{json_file}.json")
        data = util.load_json(path)

        for entry in data:
            keys = json.loads(entry['keys'])
            for key in keys:
                key = str(key[1])
                if mission_data.get(key):
                    entry['prev_text'] = entry['text']
                    entry['text'] = util.add_period(mission_data[key])
                    entry['new'] = False
                    break

        util.save_json(path, data)
    
    print("Done")



def main():
    # import_external_story('story/04/1026', 'https://api.github.com/repos/KevinVG207/umamusu-translate/contents/translations/story/04/1026?ref=mdb-update')

    # umapyoi_chara_ids = get_umapyoi_chara_ids()
    # apply_umapyoi_character_profiles(umapyoi_chara_ids)
    # apply_umapyoi_outfits(umapyoi_chara_ids)

    apply_gametora_skills()
    apply_gametora_missions()
    apply_gametora_title_missions()

if __name__ == "__main__":
    main()
