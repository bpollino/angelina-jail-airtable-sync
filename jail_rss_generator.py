#!/usr/bin/env python3

import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom
from bs4 import BeautifulSoup
from datetime import datetime
import re
import os
import csv

# Configuration
JAIL_URL = "https://www.angelinacounty.net/injail/"
AIRTABLE_API_KEY = os.getenv('AIRTABLE_API_KEY')  # Load from environment variable
AIRTABLE_BASE_ID = 'appBn4Xs7GdnheynS'
AIRTABLE_TABLE_NAME = 'tblq3cgwhhPPjffEi'  # Use the table ID, not the display name

def extract_race_ethnicity_age(demographics):
    age = ''
    race = ''
    ethnicity = ''
    info = demographics.get('age', '')
    for line in info.split('\n'):
        line = line.strip()
        if line.startswith('Age:'):
            age = line.replace('Age:', '').strip()
        elif line.startswith('Race:'):
            race = line.replace('Race:', '').strip()
        elif line.startswith('Ethnicity:'):
            ethnicity = line.replace('Ethnicity:', '').strip()
        elif line and not race and not ethnicity and not age:
            age = line
    age = ''.join(filter(str.isdigit, age))
    return race, ethnicity, age

def get_existing_jailids_from_airtable():
    url = f'https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}'
    headers = {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}',
    }
    jailids = set()
    offset = None
    while True:
        params = {}
        if offset:
            params['offset'] = offset
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            for record in data.get('records', []):
                jailid = record['fields'].get('JailID')
                if jailid:
                    jailids.add(str(jailid))
            offset = data.get('offset')
            if not offset:
                break
        else:
            print("Error fetching Airtable records:", response.text)
            break
    return jailids

def get_all_airtable_jailid_records():
    url = f'https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}'
    headers = {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}',
    }
    jailid_to_record = {}
    offset = None
    while True:
        params = {}
        if offset:
            params['offset'] = offset
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            for record in data.get('records', []):
                jailid = record['fields'].get('JailID')
                released = record['fields'].get('Released')
                if jailid:
                    jailid_to_record[str(jailid)] = {'id': record['id'], 'Released': released}
            offset = data.get('offset')
            if not offset:
                break
        else:
            print("Error fetching Airtable records:", response.text)
            break
    return jailid_to_record

def get_jail_table():
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        print("Fetching jail table...")
        response = requests.get(JAIL_URL, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        tables = soup.find_all('table')
        if not tables:
            print("No tables found on the page")
            return []

        for table in tables:
            header_row = table.find('tr')
            if not header_row:
                continue
            headers_list = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
            expected_headers = ['Name', 'Sex', 'Height', 'Weight', 'Eye Color', 'Hair Color', 'Booking Date']
            if not all(header in headers_list for header in expected_headers):
                continue

            rows = table.find_all('tr')[1:]
            inmates = []
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all(['td', 'th'])]
                if len(cells) < 7:
                    continue
                try:
                    name = cells[0].strip()
                    sex = cells[1].strip()
                    height = cells[2].strip()
                    weight = cells[3].strip()
                    eye_color = cells[4].strip()
                    hair_color = cells[5].strip()
                    booking_date = cells[6].strip()
                    jailid = None
                    onclick_attr = row.get('onclick', '')
                    jailid_match = re.search(r'jailid=(\d{6})', onclick_attr)
                    if jailid_match:
                        jailid = jailid_match.group(1)
                    detail_link = None
                    if jailid:
                        detail_link = f'https://www.angelinacounty.net/injail/inmate/?jailid={jailid}'
                    if (name and len(name) > 3 and 
                        sex in ['Male', 'Female'] and
                        booking_date and '/' in booking_date):
                        try:
                            booking_datetime = datetime.strptime(booking_date, '%m/%d/%Y')
                        except ValueError:
                            continue
                        mugshot_url = None
                        aliases = []
                        tattoos = []
                        demographics = {}
                        offenses = []
                        if detail_link:
                            try:
                                detail_resp = requests.get(detail_link, headers=headers, timeout=20)
                                detail_resp.raise_for_status()
                                detail_soup = BeautifulSoup(detail_resp.content, 'html.parser')
                                mugshot_url = None
                                inmate_image_div = detail_soup.find('div', class_='inmate-image')
                                if inmate_image_div:
                                    img_tag = inmate_image_div.find('img')
                                    if img_tag and img_tag.get('src'):
                                        mugshot_url = img_tag['src']
                                        if not mugshot_url.startswith('http'):
                                            mugshot_url = 'https://www.angelinacounty.net' + mugshot_url
                                details_div = detail_soup.find('div', class_='inmate-details')
                                if details_div:
                                    p_tag = details_div.find('p')
                                    if p_tag:
                                        for line in p_tag.decode_contents().split('<br>'):
                                            line = BeautifulSoup(line, 'html.parser').get_text().strip()
                                            if ':' in line:
                                                k, v = line.split(':', 1)
                                                demographics[k.strip().lower().replace(' ', '_')] = v.strip()
                                offense_table = detail_soup.find('table', class_='table-mobile-full')
                                if offense_table:
                                    rows = offense_table.find_all('tr')
                                    for tr in rows[1:]:
                                        tds = tr.find_all('td')
                                        if len(tds) == 5:
                                            offense = {
                                                'charge': tds[0].get_text(strip=True),
                                                'degree': tds[1].get_text(strip=True),
                                                'bond': tds[2].get_text(strip=True),
                                                'hold_reason': tds[3].get_text(strip=True),
                                                'agency': tds[4].get_text(strip=True)
                                            }
                                            offenses.append(offense)
                                alias_box = detail_soup.find('div', class_='box-content', string=None)
                                if alias_box:
                                    alias_title = alias_box.find('h6', string=re.compile('Known Aliases'))
                                    if alias_title:
                                        ul = alias_box.find('ul')
                                        if ul:
                                            aliases = [li.get_text(strip=True) for li in ul.find_all('li')]
                                tattoo_box = None
                                for box in detail_soup.find_all('div', class_='box-content'):
                                    title = box.find('h6')
                                    if title and 'Scars/Marks/Tattoos' in title.get_text():
                                        tattoo_box = box
                                        break
                                if tattoo_box:
                                    ul = tattoo_box.find('ul')
                                    if ul:
                                        tattoos = [li.get_text(strip=True) for li in ul.find_all('li')]
                            except Exception as e:
                                print(f"Error scraping detail page for {name}: {e}")
                        inmate = {
                            'name': name,
                            'sex': sex,
                            'height': height,
                            'weight': weight,
                            'eye_color': eye_color,
                            'hair_color': hair_color,
                            'booking_date': booking_date,
                            'booking_datetime': booking_datetime,
                            'detail_link': detail_link,
                            'mugshot_url': mugshot_url,
                            'aliases': aliases,
                            'tattoos': tattoos,
                            'demographics': demographics,
                            'offenses': offenses,
                            'jailid': jailid
                        }
                        inmates.append(inmate)
                except Exception as e:
                    print(f"Error parsing row: {cells} - {e}")
                    continue
            if inmates:
                inmates.sort(key=lambda x: x['booking_datetime'], reverse=True)
                return inmates
        return []
    except requests.RequestException as e:
        print(f"Error fetching jail data: {e}")
        return []
    except Exception as e:
        print(f"Error parsing jail data: {e}")
        return []

def create_airtable_record(inmate):
    url = f'https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}'
    headers = {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}',
        'Content-Type': 'application/json'
    }
    demographics = inmate.get('demographics') or {}
    race, ethnicity, age = extract_race_ethnicity_age(demographics)
    offenses = inmate.get('offenses', [])
    offense_list = [off.get('charge', '') for off in offenses]
    degree_list = [off.get('degree', '') for off in offenses]
    bond_list = [off.get('bond', '') for off in offenses]
    hold_list = [off.get('hold_reason', '') for off in offenses]
    agency_list = list({off.get('agency', '') for off in offenses if off.get('agency', '')})
    data = {
        "fields": {
            'JailID': str(inmate.get('jailid', '')),
            'Name': inmate.get('name', ''),
            'Sex': inmate.get('sex', ''),
            'Race': race,
            'Ethnicity': ethnicity,
            'Height': inmate.get('height', ''),
            'Weight': inmate.get('weight', ''),
            'Eye Color': inmate.get('eye_color', ''),
            'Hair Color': inmate.get('hair_color', ''),
            'Booking Date': inmate.get('booking_date', ''),
            'Detail Link': inmate.get('detail_link', ''),
            'Mugshot URL': inmate.get('mugshot_url', ''),
            'Known Aliases': ', '.join(inmate.get('aliases', [])),
            'Scars/Marks/Tattoos': ', '.join(inmate.get('tattoos', [])),
            'Age': age,
            'Offenses': '; '.join(offense_list),
            'Degrees': '; '.join(degree_list),
            'Bond Amounts': '; '.join(bond_list),
            'Hold Reasons': '; '.join(hold_list),
            'Arresting Agencies': '; '.join(agency_list)
        }
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200 or response.status_code == 201:
        print(f"Added inmate {inmate.get('name', '')} (JailID: {inmate.get('jailid', '')}) to Airtable.")
    else:
        print(f"Error adding inmate {inmate.get('name', '')}: {response.text}")

def update_released_in_airtable(missing_jailids, jailid_to_record):
    url = f'https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}'
    headers = {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}',
        'Content-Type': 'application/json'
    }
    released_date = datetime.now().strftime('%Y-%m-%d')
    for jailid in missing_jailids:
        record_info = jailid_to_record.get(jailid)
        if record_info and not record_info.get('Released'):
            record_id = record_info['id']
            patch_url = f"{url}/{record_id}"
            data = {
                "fields": {
                    "Released": released_date
                }
            }
            patch_resp = requests.patch(patch_url, headers=headers, json=data)
            if patch_resp.status_code == 200:
                print(f"Marked JailID {jailid} as released on {released_date}")
            else:
                print(f"Error updating release for JailID {jailid}: {patch_resp.text}")

def main():
    print("Starting Airtable sync...")
    inmates = get_jail_table()
    if inmates:
        print(f"Successfully found {len(inmates)} inmates")
        jailid_to_record = get_all_airtable_jailid_records()
        existing_jailids = set(jailid_to_record.keys())
        current_jailids = set(str(inmate.get('jailid')) for inmate in inmates if inmate.get('jailid'))
        new_inmates = [inmate for inmate in inmates if str(inmate.get('jailid')) not in existing_jailids]
        print(f"Found {len(new_inmates)} new inmates not in Airtable")
        for inmate in new_inmates:
            create_airtable_record(inmate)
        missing_jailids = existing_jailids - current_jailids
        print(f"Found {len(missing_jailids)} released inmates to update")
        update_released_in_airtable(missing_jailids, jailid_to_record)
        if not new_inmates:
            print("No new inmates to add to Airtable.")
    else:
        print("No inmate data found - nothing added to Airtable")
        return False
    return True

if __name__ == "__main__":
    success = main()
    if not success:
        print("Python script completed with errors")
        exit(1)
    else:
        print("Python script completed successfully")