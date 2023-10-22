import json
import os
import sys
from datetime import datetime, timedelta
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

    delete_jobs = config["delete_jobs"]
    if delete_jobs == None:
        logging.error("delete_jobs not set in config.json")
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

    now = datetime.now()
    yesterday = now - timedelta(days=1)
    yesterday_iso = yesterday.strftime("%Y-%m-%dT%H:%M:%SZ")

    # get all the restore points from yesterday
    try:
        restore_points = vec.get(f"RestorePoints?from={yesterday_iso}", False)
    except:
        logging.error("Error getting restore points")
        sys.exit(1)

    if save == True:
        save_json(restore_points, "restore_points.json")

    job_ids = [x["jobId"] for x in restore_points["results"]]
    job_ids = list(set(job_ids))

    restore_points_filtered = []

    for i in job_ids:
        temp = []
        for x in restore_points["results"]:
            if i == x["jobId"]:
                temp.append(x)
        restore_points_filtered.append(temp[0])

    restore_points = {"results": restore_points_filtered}

    protected_sites = []
    protected_teams = []
    sub_string = "/v7"

    # get all the protected sites and teams from the restore points
    # doing it this way means that I don't have filter the protected sites/teams
    logging.info("Getting protected sites and teams")
    for point in restore_points["results"]:
        if point["isSharePoint"] == True:
            url = point["_links"]["protectedSites"]["href"]
            url = url.replace(sub_string, "")
            try:
                ps = vec.get(url, False)
            except:
                logging.error(
                    f"Error getting protected sites for restore point {point['id']} in job {point['jobId']}"
                )
                sys.exit(1)
            data = {
                "point_id": point["id"],
                "backup_time": point["backupTime"],
                "protected_sites": ps,
            }
            protected_sites.append(data)
        if point["isTeams"] == True:
            url = point["_links"]["protectedTeams"]["href"]
            url = url.replace(sub_string, "")
            try:
                pt = vec.get(url, False)
            except:
                logging.error(
                    f"Error getting protected teams for {point['id']} in job {point['jobId']}"
                )
                sys.exit(1)
            data = {
                "point_id": point["id"],
                "backup_time": point["backupTime"],
                "protected_teams": pt,
            }
            protected_teams.append(data)
        logging.info(
            f"Got protected sites and teams for {point['id']} in job {point['jobId']}"
        )

    if save == True:
        save_json(protected_sites, "protected_sites.json")
        save_json(protected_teams, "protected_teams.json")

    # get all the site and team ids from all the sites/teams as well as the protected sites/teams
    logging.info("Checking for sites and teams to remove")
    site_ids = []

    for x in all_sites:
        for y in x["sites"]["results"]:
            site_ids.append(y["id"])

    protected_site_ids = [
        y["siteId"] for x in protected_sites for y in x["protected_sites"]["results"]
    ]
    teams_ids = []

    for x in all_teams:
        for y in x["teams"]["results"]:
            teams_ids.append(y["id"])

    protected_teams_ids = [
        y["id"] for x in protected_teams for y in x["protected_teams"]["results"]
    ]

    sites_to_remove = []

    # check if the site id is in the M365 environment
    for i in protected_site_ids:
        if i not in site_ids:
            sites_to_remove.append(i)

    teams_to_remove = []

    # check if the team id is in the M365 environment
    for i in protected_teams_ids:
        if i not in teams_ids:
            teams_to_remove.append(i)

    if len(sites_to_remove) == 0 and len(teams_to_remove) == 0:
        logging.info("No teams or sites to remove, exiting")
        sys.exit(1)

    # get the jobs
    logging.info("Getting job data")
    try:
        jobs = vec.get("Jobs", False)
    except:
        logging.error("Error getting job data")
        sys.exit(1)
    else:
        logging.info("Got jobs OK")

    backup_job_items = []

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
        filter = []
        for i in res:
            if i["type"] == "Site" and i["site"]["id"] in sites_to_remove:
                filter.append(i)
            if i["type"] == "Team" and i["team"]["id"] in teams_to_remove:
                filter.append(i)
        if len(filter) == 0:
            continue
        data = {"job_name": j["name"], "job_id": j["id"], "items": filter}
        backup_job_items.append(data)

    if save == True:
        save_json(backup_job_items, "backup_job_items.json")

    site_delete_info = []
    teams_delete_info = []

    # loop through the sites to remove and the backup job items
    for i in sites_to_remove:
        for b in backup_job_items:
            for t in b["items"]:
                if t["type"] == "Site":
                    if i == t["site"]["id"]:
                        data = {
                            "job_name": b["job_name"],
                            "job_id": b["job_id"],
                            "site_id": t["id"],
                        }
                        site_delete_info.append(data)

    for i in teams_to_remove:
        for b in backup_job_items:
            for t in b["items"]:
                if t["type"] == "Team":
                    if i == t["team"]["id"]:
                        data = {
                            "job_name": b["job_name"],
                            "job_id": b["job_id"],
                            "team_id": t["id"],
                        }
                        teams_delete_info.append(data)

    teams_seen = set()
    teams_delete_info = [
        x
        for x in teams_delete_info
        if x["team_id"] not in teams_seen and not teams_seen.add(x["team_id"])
    ]
    sites_seen = set()
    site_delete_info = [
        x
        for x in site_delete_info
        if x["site_id"] not in sites_seen and not sites_seen.add(x["site_id"])
    ]

    if len(site_delete_info) == 0:
        logging.info("No sites to delete")
    else:
        for i in site_delete_info:
            logging.info(
                f"Site {i['site_id']} in job {i['job_name']} will be removed from job"
            )

    if len(teams_delete_info) == 0:
        logging.info("No teams to delete")
    else:
        for i in teams_delete_info:
            logging.info(
                f"Team {i['team_id']} in job {i['job_name']} will be removed from job"
            )

    if dry_run == True:
        logging.info("Dry run enabled, exiting")
        sys.exit(1)

    auth_headers = vec.get_request_header()

    if len(site_delete_info) > 0:
        logging.info("Deleting sites that are no longer in the M365 environment")
        for i in site_delete_info:
            current_job_data = vec.get(f"jobs/{i['job_id']}", False)
            url = current_job_data["_links"]["selectedItems"]["href"]
            url = url.replace(sub_string, "")
            selected_items = vec.get(url, False)
            if len(selected_items) == 1:
                try:
                    port = vec.get_port()
                    url = f"https://{address}:{port}/{api_version}/jobs/{i['team_id']}/disable"
                    res = requests.post(url, headers=auth_headers, verify=False)
                except:
                    logging.error(
                        f"Error disabling job {i['job_id']} for site {i['site_id']}"
                    )
                    sys.exit(1)
                logging.info(
                    f"Job {i['job_name']} only has one item, it has been disabled, job will need to be manually deleted"
                )
                continue
            else:
                logging.info(f"Deleting site {i['site_id']} from job {i['job_name']}")
                address = vec.address
                port = vec.get_port()
                api_version = vec.get_api_version()
                url = f"https://{address}:{port}/{api_version}/jobs/{i['job_id']}/SelectedItems?ids={i['site_id']}"
                res = requests.delete(url, headers=auth_headers, verify=False)
                if res.status_code != 204:
                    logging.error(f"Error deleting site {i['site_id']}")
                    logging.error(res.text)
                    sys.exit(1)
                else:
                    logging.info(f"Deleted site {i['site_id']}")

    if len(teams_delete_info) > 0:
        logging.info("Deleting teams that are no longer in the M365 environment")
        for i in teams_delete_info:
            current_job_data = vec.get(f"jobs/{i['job_id']}", False)
            url = current_job_data["_links"]["selectedItems"]["href"]
            url = url.replace(sub_string, "")
            selected_items = vec.get(url, False)
            if len(selected_items) == 1:
                try:
                    port = vec.get_port()
                    url = f"https://{address}:{port}/{api_version}/jobs/{i['team_id']}/disable"
                    res = requests.post(url, headers=auth_headers, verify=False)
                except Exception as e:
                    logging.error(
                        f"Error disabling job {i['job_id']} for site {i['team_id']}"
                    )
                    logging.error(e)
                    sys.exit(1)
                logging.info(
                    f"Job {i['job_name']} only has one item, it has been disabled, job will need to be manually deleted"
                )
                continue
            else:
                logging.info(f"Deleting team {i['team_id']} from job {i['job_name']}")
                address = vec.address
                port = vec.get_port()
                api_version = vec.get_api_version()
                url = f"https://{address}:{port}/{api_version}/jobs/{i['job_id']}/SelectedItems?ids={i['team_id']}"
                res = requests.delete(url, headers=auth_headers, verify=False)
                if res.status_code != 204:
                    logging.error(f"Error deleting team {i['team_id']}")
                    logging.error(res.text)
                    sys.exit(1)
                else:
                    logging.info(f"Deleted team {i['team_id']}")


if __name__ == "__main__":
    main()
