import json
import os
import sys
from veeam_easy_connect import VeeamEasyConnect
import requests
import urllib3
import click

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import logging

logging.basicConfig(
    filename="app.log",
    filemode="w",
    format="format='%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


def get_config():
    with open("config.json", "r") as f:
        config = json.load(f)
    return config


def save_json(data, file_name):
    with open(file_name, "w") as outfile:
        json.dump(data, outfile)

def job_updater(dry_run, address, vec, api_version, site_delete_info, auth_headers, sub_string, data_type):
    if len(site_delete_info) > 0:
        logging.info("Deleting sites that are no longer in the M365 environment")
        for i in site_delete_info:
            job_id = i["job_id"]
            job_name = i["job_name"]
            veeam_site_id = i["id"]
            if data_type == "site":
                data_id = i["site"]["id"]
                data_name = i["site"]["name"]
            elif data_type == "team":
                data_id = i["team"]["id"]
                data_name = i["team"]["name"]
            current_job_data = vec.get(f"jobs/{job_id}", False)
            url = current_job_data["_links"]["selectedItems"]["href"]
            url = url.replace(sub_string, "")
            selected_items = vec.get(url, False)
            if len(selected_items) == 1:
                logging.info(
                    f"Job {job_name} only has one item, it will be disabled, job will need to be manually deleted"
                )
                try:
                    port = vec.get_port()
                    url = (
                        f"https://{address}:{port}/{api_version}/jobs/{job_id}/disable"
                    )
                    if dry_run == True:
                        logging.info(f"Dry run, not disabling job {job_name}")
                    else:
                        logging.info(f"Sending disable request to {url}")
                        res = requests.post(url, headers=auth_headers, verify=False)
                except:
                    if data_type == "site":
                        logging.error(
                                f"Error disabling job {job_name}, id: {job_id} for site {data_name}, id: {data_id}"      
                        )
                    else:
                        logging.error(
                                f"Error disabling job {job_name}, id: {job_id} for team {data_name}, id: {data_name}"      
                        )
                    sys.exit(1)
            else:
                if data_type == "site":
                    logging.info(
                        f"Deleting site {data_name}, id: {data_id} from job {job_name}, id: {job_id}"
                    )
                else:
                    logging.info(
                        f"Deleting team {data_name}, id: {data_id} from job {job_name}, id: {job_id}"
                    )
                address = vec.address
                port = vec.get_port()
                api_version = vec.get_api_version()
                url = f"https://{address}:{port}/{api_version}/jobs/{job_id}/SelectedItems?ids={veeam_site_id}"
                logging.info(f"Sending delete request to {url}")
                if dry_run == True:
                    if data_type == "site":
                        logging.info(f"Dry run, not deleting site {data_name}")
                    else: 
                        logging.info(f"Dry run, not deleting team {data_name}")
                else:
                    logging.info(f"Sending delete request to {url}")
                    res = requests.delete(url, headers=auth_headers, verify=False)
                if res.status_code != 204:
                    if data_type == "site":
                        logging.error(f"Error deleting site {data_name}, id: {data_id}")
                    else:
                        logging.error(f"Error deleting team {data_name}, id: {data_id}")
                    logging.error(res.text)
                    sys.exit(1)
                else:
                    if data_type == "site":
                        logging.info(f"Deleted site {data_name}, id: {data_id}")
                    else:
                        logging.info(f"Deleted team {data_name}, id: {data_id}")

def item_checker(all_sites, protected_items, data_type):
    deleted_info = []
    other_type = "site" if data_type == "sites" else "team"
    for i in protected_items:
        found = False
        for j in all_sites:
            for k in j[f"{data_type}"]["results"]:
                if i[f"{other_type}"]["id"] == k["id"]:
                    found = True
                    break
        if found == False:
            deleted_info.append(i)
    return deleted_info

@click.command()
@click.option(
    "--dry-run",
    "-d",
    is_flag=True,
    help="Dry run, don't delete anything",
)
@click.option(
    "--save",
    "-s",
    is_flag=True,
    help="Save the outputs to a json files",
)
def main(dry_run, save):
    config = get_config()

    password = os.environ.get("VB365_PASSWORD")
    if password == None:
        logging.error("VB365_PASSWORD environment variable not set")
        sys.exit(1)

    username = config["username"]
    if username == None:
        logging.error("username not set in config.json")
        sys.exit(1)

    address = config["vb365_address"]
    if address == None:
        logging.error("vb365_address not set in config.json")
        sys.exit(1)

    vec = VeeamEasyConnect(username, password, False)

    vec.o365().update_api_version("v7")
    api_version = vec.get_api_version()
    vec.url_end = vec.url_end.replace("v6", "v7")

    try:
        vec.login(address)
    except Exception as e:
        logging.error(e)
        sys.exit(1)
    else:
        logging.info("Logged in successfully")

    all_sites = []
    all_teams = []

    # get all the organizations
    orgs = vec.get("Organizations", False)
    if len(orgs) == 0:
        logging.error("No organizations found")
        sys.exit(1)
    else:
        org_names = [x["name"] for x in orgs]
        logging.info(f"Found {len(orgs)} organizations: {org_names}")

    if save == True:
        save_json(orgs, "orgs.json")
    # get all the sites and teams for each organization
    logging.info("Getting sites and teams for each organization")
    for org in orgs:
        org_id = org["id"]
        org_name = org["name"]
        try:
            org_teams = vec.get(
                f"Organizations/{org_id}/Teams?dataSource=PreferLocalResynced", False
            )
        except:
            logging.error(f"Error getting teams for {org_name}")
            sys.exit(1)
        try:
            org_sites = vec.get(
                f"Organizations/{org_id}/Sites?dataSource=PreferLocalResynced", False
            )
        except:
            logging.error(f"Error getting sites for {org_name}")
            sys.exit(1)
        temp_sites = []
        for i in org_sites["results"]:
            if i["isAvailable"] == True:
                temp_sites.append(i)
        teams_data = {
            "org_id": org_id,
            "org_name": org_name,
            "teams": org_teams,
        }
        sites_data = {
            "org_id": org_id,
            "org_name": org_name,
            "sites": {"results": temp_sites},
        }
        all_teams.append(teams_data)
        all_sites.append(sites_data)

    if save == True:
        save_json(all_teams, "all_teams.json")
        save_json(all_sites, "all_sites.json")

    # get the jobs
    logging.info("Getting job data")
    try:
        jobs = vec.get("Jobs", False)
    except:
        logging.error("Error getting job data")
        sys.exit(1)
    else:
        logging.info("Got jobs OK")

    protected_teams = []
    protected_sites = []

    # for each job get the selected items
    logging.info("Getting selected items from jobs")
    for j in jobs:
        url = f"jobs/{j['id']}/SelectedItems"
        try:
            res = vec.get(url, False)
        except:
            logging.error(f"Error in getting selected items from job {j['id']}")
            sys.exit(1)
        else:
            logging.info(f"Got selected items from job {j['id']}")
        for i in res:
            if i["type"] == "Site":
                i["job_name"] = j["name"]
                i["job_id"] = j["id"]
                protected_sites.append(i)
            if i["type"] == "Team":
                i["job_name"] = j["name"]
                i["job_id"] = j["id"]
                i["team_name"] = i["team"]["displayName"]
                protected_teams.append(i)

    if save == True:
        save_json(protected_sites, "protected_sites.json")
        save_json(protected_teams, "protected_teams.json")

    # get all the site and team ids from all the sites/teams as well as the protected sites/teams
    logging.info("Checking for sites and teams to remove")

    # check if the site id is in the M365 environment
    site_delete_info = item_checker(all_sites, protected_sites, "sites")

    # check if the team id is in the M365 environment
    teams_delete_info = item_checker(all_teams, protected_teams, "teams")

    if len(site_delete_info) == 0 and len(teams_delete_info) == 0:
        logging.info("No teams or sites to remove, exiting")
        sys.exit(1)

    if len(site_delete_info) > 0:
        for i in site_delete_info:
            logging.info(
                f"Site {i['site']['name']}, id: {i['site']['id']} is not in the M365 environment"
            )

    if len(teams_delete_info) > 0:
        for i in teams_delete_info:
            logging.info(
                f"Team {i['team_name']}, id: {i['team']['id']} is not in the M365 environment"
            )

    if save == True:
        save_json(site_delete_info, "site_to_delete.json")
        save_json(teams_delete_info, "teams_to_delete.json")

    auth_headers = vec.get_request_header()

    sub_string = "/v7/"

    # For sites
    job_updater(dry_run, address, vec, api_version, site_delete_info, auth_headers, sub_string, "site")

    # For teams
    job_updater(dry_run, address, vec, api_version, teams_delete_info, auth_headers, sub_string, "team")

    logging.info("Done")

if __name__ == "__main__":
    main()
