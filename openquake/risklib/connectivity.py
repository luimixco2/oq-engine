# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2023, GEM Foundation
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake.  If not, see <http://www.gnu.org/licenses/>.

# This module was prepared by:

# @author 1 . Astha Poudel, Early Stage Researcher, PhD candidate
# Aristotle University of Thessaloniki/Université Grenoble Alpes

# @author 2 . Anirudh Rao

# The present work has been done in the framework of grant agreement No. 813137
# funded by the European Commission ITN-Marie Sklodowska-Curie project
# “New Challenges for Urban Engineering Seismology (URBASIS-EU)”.
# @author 1 has been funded by this project

import pandas as pd
import numpy as np
import networkx as nx


def get_exposure_df(dstore):
    assetcol = dstore["assetcol"]
    tagnames = sorted(tn for tn in assetcol.tagnames if tn != "id")
    tags = {t: getattr(assetcol.tagcol, t) for t in tagnames}
    exposure_df = (
        assetcol.to_dframe()
        .replace(
            {
                tagname: {i: tag for i, tag in enumerate(tags[tagname])}
                for tagname in tagnames
            }
        )
    ).set_index("id")

    # FIXME: Needs to be checked. It gives an error if this is not done.
    if 'weights' in exposure_df.columns:
        exposure_df['weights'] = exposure_df['weights'].astype(float)

    return exposure_df


def classify_nodes(exposure_df):
    # Classifying the nodes accodingly to compute performance indicator in
    # global and local scale

    # TAZ is the acronym of "Traffic Analysis Zone"
    # user can write both as well
    TAZ_nodes = exposure_df.loc[(exposure_df.purpose == "TAZ") | (
        exposure_df.purpose == "both")].index.to_list()

    # ## Maybe we can write supply or source and demand or sink so that user
    #    can use whatever they want to
    # source_nodes = exposure_df.loc[exposure_df[
    #     'purpose'].isin(['source', 'supply'])].index.to_list()
    source_nodes = exposure_df.loc[
        exposure_df.purpose == "source"].index.to_list()
    demand_nodes = exposure_df.loc[
        exposure_df.purpose == "demand"].index.to_list()
    eff_nodes = exposure_df.loc[exposure_df.type == "node"].index.to_list()

    # We should raise an error if the exposure nodes contain at the same time
    # taz/both and demand/supply
    if TAZ_nodes and demand_nodes:
        raise ValueError(
            'The exposure can contain either taz/both nodes or'
            ' demand/supply nodes, but not both kinds at the same time.')

    return TAZ_nodes, source_nodes, demand_nodes, eff_nodes


def get_graph_type(exposure_df):
    # This is to handle different type of graph. If nothing is provided, OQ
    # will assume as simple undirected graph
    # If there is a column name "graphtype" they can specify the type in any
    # row
    if 'graphtype' in exposure_df.columns and exposure_df[
            'graphtype'].isin(['directed']).any():
        g_type = "DiGraph"
    elif 'graphtype' in exposure_df.columns and exposure_df[
            'graphtype'].isin(['multi']).any():
        g_type = "MultiGraph"
    elif 'graphtype' in exposure_df.columns and exposure_df[
            'graphtype'].isin(['multidirected']).any():
        g_type = "MultiDiGraph"
    else:
        g_type = "Graph"

    return g_type


def create_original_graph(exposure_df, g_type):
    # Create the original graph and add edge and node attributes.
    G_original = nx.from_pandas_edgelist(
        exposure_df.loc[exposure_df.type == "edge"],
        source="start_node",
        target="end_node",
        edge_attr=True, create_using=getattr(nx, g_type)()
    )
    # This is done for the cases where there might be a disconnected node with
    # no edges and are not added in the G_original previously
    for _, row in exposure_df.loc[exposure_df.type == "node"].iterrows():
        if row["id"] not in G_original.nodes:
            G_original.add_node(row["id"], **row)
    # Adding the attribute of the nodes
    nx.set_node_attributes(
        G_original, exposure_df.loc[
            exposure_df.type == "node"].to_dict("index")
    )

    return G_original


def get_damage_df(dstore, exposure_df):
    # Extractung the damage data from component level analysis
    agg_keys = pd.DataFrame({"id": [key.decode()
                                    for key in dstore["agg_keys"][:]]})
    damage_df = (
        dstore.read_df("risk_by_event", "event_id")
        .join(agg_keys.id, on="agg_id")
        .dropna(subset=["id"])
        .set_index("id", append=True)
        .drop(columns=["agg_id", "loss_id"])
        .sort_index(level=["event_id", "id"])
        .astype(int)
        .join(exposure_df)
        .assign(is_functional=lambda x: x.non_operational == 0)
    )[["type", "start_node", "end_node", "is_functional", "taxonomy"]]

    return damage_df


def analyze_taz_nodes(dstore, exposure_df, G_original, TAZ_nodes, eff_nodes,
                      damage_df, g_type, calculation_mode):
    taz_nodes_analysis_results = {}
    (taz_cl, node_el,
        event_connectivity_loss_pcl,
        event_connectivity_loss_wcl,
        event_connectivity_loss_eff) = ELWCLPCLloss_TAZ(
        exposure_df, G_original, TAZ_nodes, eff_nodes, damage_df, g_type)
    sum_connectivity_loss_pcl = event_connectivity_loss_pcl['PCL'].sum()
    sum_connectivity_loss_wcl = event_connectivity_loss_wcl['WCL'].sum()
    sum_connectivity_loss_eff = event_connectivity_loss_eff['EL'].sum()

    if calculation_mode == "event_based_damage":
        inv_time = dstore["oqparam"].investigation_time
        ses_per_ltp = dstore["oqparam"].ses_per_logic_tree_path
        num_lt_samples = dstore["oqparam"].number_of_logic_tree_samples
        eff_inv_time = inv_time * ses_per_ltp * num_lt_samples
        avg_connectivity_loss_pcl = (
            sum_connectivity_loss_pcl / eff_inv_time)
        avg_connectivity_loss_wcl = sum_connectivity_loss_wcl/eff_inv_time
        avg_connectivity_loss_eff = sum_connectivity_loss_eff/eff_inv_time

    elif calculation_mode == "scenario_damage":
        num_events = len(damage_df.reset_index().event_id.unique())
        avg_connectivity_loss_pcl = sum_connectivity_loss_pcl / num_events
        avg_connectivity_loss_wcl = sum_connectivity_loss_wcl / num_events
        avg_connectivity_loss_eff = sum_connectivity_loss_eff / num_events
        taz_cl.loc[:, "PCL_node"] = taz_cl["PCL_node"].apply(
            lambda x: x/num_events)
        taz_cl.loc[:, "WCL_node"] = taz_cl["WCL_node"].apply(
            lambda x: x/num_events)
        node_el.loc[:, "EL"] = node_el["EL"].apply(lambda x: x/num_events)

    taz_cl.drop(columns=['ordinal'], inplace=True)
    node_el.drop(columns=['ordinal'], inplace=True)

    for result in [
            'avg_connectivity_loss_pcl', 'avg_connectivity_loss_wcl',
            'avg_connectivity_loss_eff',
            'event_connectivity_loss_pcl', 'event_connectivity_loss_wcl',
            'event_connectivity_loss_eff',
            'taz_cl', 'node_el']:
        taz_nodes_analysis_results[result] = locals()[result]

    return taz_nodes_analysis_results


def analyze_demand_nodes(dstore, exposure_df, G_original, eff_nodes,
                         demand_nodes, source_nodes, damage_df, g_type,
                         calculation_mode):
    demand_nodes_analysis_results = {}
    (dem_cl, node_el, event_connectivity_loss_ccl,
        event_connectivity_loss_pcl, event_connectivity_loss_wcl,
        event_connectivity_loss_eff) = ELWCLPCLCCL_demand(
        exposure_df, G_original, eff_nodes, demand_nodes, source_nodes,
        damage_df, g_type)
    sum_connectivity_loss_ccl = event_connectivity_loss_ccl['CCL'].sum()
    sum_connectivity_loss_pcl = event_connectivity_loss_pcl['PCL'].sum()
    sum_connectivity_loss_wcl = event_connectivity_loss_wcl['WCL'].sum()
    sum_connectivity_loss_eff = event_connectivity_loss_eff['EL'].sum()

    if calculation_mode == "event_based_damage":
        inv_time = dstore["oqparam"].investigation_time
        ses_per_ltp = dstore["oqparam"].ses_per_logic_tree_path
        num_lt_samples = dstore["oqparam"].number_of_logic_tree_samples
        eff_inv_time = inv_time * ses_per_ltp * num_lt_samples
        avg_connectivity_loss_ccl = (
            sum_connectivity_loss_ccl / eff_inv_time)
        avg_connectivity_loss_pcl = (
            sum_connectivity_loss_pcl / eff_inv_time)
        avg_connectivity_loss_wcl = (
            sum_connectivity_loss_wcl / eff_inv_time)
        avg_connectivity_loss_eff = (
            sum_connectivity_loss_eff / eff_inv_time)

    elif calculation_mode == "scenario_damage":
        num_events = len(damage_df.reset_index().event_id.unique())
        avg_connectivity_loss_ccl = sum_connectivity_loss_ccl / num_events
        avg_connectivity_loss_pcl = sum_connectivity_loss_pcl / num_events
        avg_connectivity_loss_wcl = sum_connectivity_loss_wcl / num_events
        avg_connectivity_loss_eff = sum_connectivity_loss_eff/num_events
        dem_cl.loc[:, "CCL_node"] = dem_cl["CCL_node"].apply(
            lambda x: x/num_events)
        dem_cl.loc[:, "PCL_node"] = dem_cl["PCL_node"].apply(
            lambda x: x/num_events)
        dem_cl.loc[:, "WCL_node"] = dem_cl["WCL_node"].apply(
            lambda x: x/num_events)
        node_el.loc[:, "EL"] = node_el["EL"].apply(
            lambda x: x/num_events)

    dem_cl.drop(columns=['ordinal'], inplace=True)
    node_el.drop(columns=['ordinal'], inplace=True)

    for result in [
            'avg_connectivity_loss_ccl', 'avg_connectivity_loss_pcl',
            'avg_connectivity_loss_wcl', 'avg_connectivity_loss_eff',
            'event_connectivity_loss_ccl', 'event_connectivity_loss_pcl',
            'event_connectivity_loss_wcl', 'event_connectivity_loss_eff',
            'dem_cl', 'node_el']:
        demand_nodes_analysis_results[result] = locals()[result]

    return demand_nodes_analysis_results


def analyze_generic_nodes(dstore, exposure_df, G_original, eff_nodes,
                          damage_df, g_type, calculation_mode):
    generic_nodes_analysis_results = {}
    node_el, event_connectivity_loss_eff = EL_node(
        exposure_df, G_original, eff_nodes, damage_df, g_type)
    sum_connectivity_loss_eff = event_connectivity_loss_eff['EL'].sum()

    if calculation_mode == "event_based_damage":
        inv_time = dstore["oqparam"].investigation_time
        ses_per_ltp = dstore["oqparam"].ses_per_logic_tree_path
        num_lt_samples = dstore["oqparam"].number_of_logic_tree_samples
        eff_inv_time = inv_time * ses_per_ltp * num_lt_samples
        avg_connectivity_loss_eff = sum_connectivity_loss_eff/eff_inv_time

    elif calculation_mode == "scenario_damage":
        num_events = len(damage_df.reset_index().event_id.unique())
        avg_connectivity_loss_eff = sum_connectivity_loss_eff/num_events
        node_el.loc[:, "EL"] = node_el["EL"].apply(lambda x: x/num_events)

    node_el.drop(columns=['ordinal'], inplace=True)

    for result in [
            'avg_connectivity_loss_eff',
            'event_connectivity_loss_eff',
            'node_el']:
        generic_nodes_analysis_results[result] = locals()[result]

    return generic_nodes_analysis_results


def cleanup_graph(G_original, event_damage_df, g_type):
    # Making a copy of original graph for each event for the analysis
    G = G_original.copy()

    nodes_damage_df = event_damage_df.loc[
        event_damage_df.type == "node"].droplevel(level=0)
    edges_damage_df = event_damage_df.loc[
        event_damage_df.type == "edge"].droplevel(level=0)

    # Updating the graph to remove damaged edges and nodes
    nonfunctional_edges_df = edges_damage_df.loc[
        ~edges_damage_df.is_functional]
    nonfunctional_nodes_df = nodes_damage_df.loc[
        ~nodes_damage_df.is_functional]

    # This is done to handle the the multi graph where more that one edge
    # is possible between two nodes.
    # If it is a multi graph then every edge has a key value

    if g_type == "MultiGraph" or g_type == "MultiDiGraph":
        edges_to_remove = [
            (u, v, key)
            for (u, v, key, data) in G.edges(keys=True, data=True)
            if data['id'] in nonfunctional_edges_df.index.to_list()]
    else:
        edges_to_remove = [
            (u, v) for (u, v, data) in G.edges(data=True)
            if data['id'] in nonfunctional_edges_df.index.to_list()]

    # nonfunctional_edge_tuples = list(
    #     zip(nonfunctional_edges_df.start_node,
    #         nonfunctional_edges_df.end_node)
    # )

    G.remove_edges_from(edges_to_remove)
    # G.remove_edges_from(nonfunctional_edge_tuples)
    G.remove_nodes_from(nonfunctional_nodes_df.index.to_list())

    return G


def calc_weighted_connectivity_loss(
        graph, att, nodes_from, nodes_to, wcl_table, pcl_table, ws, ns):
    # For calculating weighted connectivity loss
    # Important: if the weights is not provided, then the weights of each edges
    # is considered to be one.
    for i in nodes_to:
        if not att:
            path_lengths = [
                nx.shortest_path_length(graph, j, i)
                for j in nodes_from if nx.has_path(graph, j, i)]
            countw = sum(
                [1/path_length for path_length in path_lengths
                 if path_length != 0])
        else:
            path_lengths = [
                nx.shortest_path_length(graph, j, i, weight='weights')
                for j in nodes_from if nx.has_path(graph, j, i)]
            countw = sum(
                [1/path_length for path_length in path_lengths
                 if path_length != 0])
        wcl_table.at[i, ws] = countw * pcl_table.at[i, ns]
    return wcl_table


def calc_efficiency(graph, N, att, eff_table, eff):
    # For calculating efficiency
    # Important: If the weights is not provided, then the weights of each edges
    # is considered to be one.
    for node in graph:
        if not att:
            lengths = nx.single_source_shortest_path_length(graph, node)
            inv = [1/x for x in lengths.values() if x != 0]
            eff_node = (sum(inv))/(N-1)
        else:
            lengths = nx.single_source_dijkstra_path_length(
                graph, node, weight="weights")
            inv = [1/x for x in lengths.values() if x != 0]
            eff_node = (sum(inv))/(N-1)
        eff_table.at[node, eff] = eff_node

    if eff == 'Eff':
        # This is done so that if the initial graph has a node disconnected,
        # will raise an error when calculating the efficiency loss
        eff_table['EL'] = (
            eff_table.Eff0 - eff_table.Eff)/eff_table.Eff0.replace({0: np.nan})
        eff_table['EL'] = eff_table['EL'].fillna(0)

    return eff_table


def analysis(dstore):
    connectivity_results = {}
    oq = dstore["oqparam"]
    calculation_mode = oq.calculation_mode
    assert calculation_mode in ("event_based_damage", "scenario_damage")
    exposure_df = get_exposure_df(dstore)

    (TAZ_nodes, source_nodes,
     demand_nodes, eff_nodes) = classify_nodes(exposure_df)

    g_type = get_graph_type(exposure_df)
    exposure_df['id'] = exposure_df.index
    G_original = create_original_graph(exposure_df, g_type)
    damage_df = get_damage_df(dstore, exposure_df)

    # Calling the function according to the specification of the node type
    if TAZ_nodes:
        # if the nodes acts as both supply or demand (for example: traffic
        # analysis zone in transportation network)
        taz_nodes_analysis_results = analyze_taz_nodes(
            dstore, exposure_df, G_original, TAZ_nodes, eff_nodes, damage_df,
            g_type, calculation_mode)
        connectivity_results.update(taz_nodes_analysis_results)
    elif demand_nodes:
        # This is the classic and mostly used when supply/source and
        # demand/sink is explicity mentioned to the nodes of interest
        demand_nodes_analysis_results = analyze_demand_nodes(
            dstore, exposure_df, G_original, eff_nodes, demand_nodes,
            source_nodes, damage_df, g_type, calculation_mode)
        connectivity_results.update(demand_nodes_analysis_results)
    else:
        # if nothing is mentioned in case of scarce data or every node is
        # important and no distinction can be made
        generic_nodes_analysis_results = analyze_generic_nodes(
            dstore, exposure_df, G_original, eff_nodes, damage_df, g_type,
            calculation_mode)
        connectivity_results.update(generic_nodes_analysis_results)

    return connectivity_results


def ELWCLPCLCCL_demand(exposure_df, G_original, eff_nodes, demand_nodes,
                       source_nodes, damage_df, g_type):
    # Classic one where particular nodes are divided as supply or demand and
    # the main interest is to check the serviceability of supply to demand
    # nodes. This calculates, complete connectivity loss (CCL), weighted
    # connectivity loss (WCL), partial connectivity loss(PCL) considering the
    # demand and supply nodes provided at nodal and global level. Additionly,
    # efficiency loss globally and for each node is also calculated

    # To store the information of the performance indicators at connectivity
    # level
    dem_cl = exposure_df[
        exposure_df['purpose'] == 'demand'].iloc[:, 0:1]
    node_el = exposure_df[exposure_df['type'] == 'node'].iloc[:, 0:1]

    ccl_table = pd.DataFrame({'id': demand_nodes})
    pcl_table = pd.DataFrame({'id': demand_nodes})
    wcl_table = pd.DataFrame({'id': demand_nodes})
    eff_table = pd.DataFrame({'id': eff_nodes})

    ccl_table.set_index('id', inplace=True)
    pcl_table.set_index('id', inplace=True)
    wcl_table.set_index('id', inplace=True)
    eff_table.set_index("id", inplace=True)

    # Create an empty dataframe with columns "event_id" and
    # "CCL"/"PCL"/"WCL"/"EL"

    event_connectivity_loss_ccl = pd.DataFrame(columns=['event_id', 'CCL'])
    event_connectivity_loss_pcl = pd.DataFrame(columns=['event_id', 'PCL'])
    event_connectivity_loss_wcl = pd.DataFrame(columns=['event_id', 'WCL'])
    event_connectivity_loss_eff = pd.DataFrame(columns=['event_id', 'EL'])

    # To check the the values for each node before the earthquake event

    # For calculating complete connectivity Loss
    ccl_table['CNO'] = [1 if any(nx.has_path(G_original, j, i)
                        for j in source_nodes) else 0 for i in demand_nodes]

    # For calculating partial connectivity loss
    pcl_table['NS0'] = [sum(nx.has_path(G_original, j, i)
                        for j in source_nodes) for i in demand_nodes]

    att = nx.get_edge_attributes(G_original, 'weights')
    wcl_table = calc_weighted_connectivity_loss(
        G_original, att, source_nodes, demand_nodes, wcl_table, pcl_table,
        'WS0', 'NS0')

    N = len(G_original)
    att = nx.get_edge_attributes(G_original, 'weights')
    eff_table = calc_efficiency(G_original, N, att, eff_table, 'Eff0')

    # Now we check for every event after earthquake
    for event_id, event_damage_df in damage_df.groupby("event_id"):
        G = cleanup_graph(G_original, event_damage_df, g_type)

        # Checking if there is a path between any souce to each demand node.
        # Some demand nodes and source nodes may have been eliminated from
        # the network due to damage, so we do not need to check their
        # functionalities
        extant_source_nodes = set(source_nodes) & set(G.nodes)
        extant_demand_nodes = sorted(set(demand_nodes) & set(G.nodes))
        extant_eff_nodes = sorted(set(eff_nodes) & set(G.nodes))

        # If demand nodes are damaged itself (Example, building collapsed where
        # demand node is considered)

        ccl_table.loc[~ccl_table.index.isin(extant_demand_nodes), 'CN'] = 0
        pcl_table.loc[~pcl_table.index.isin(extant_demand_nodes), 'NS'] = 0
        wcl_table.loc[~wcl_table.index.isin(extant_demand_nodes), 'WS'] = 0
        eff_table.loc[~eff_table.index.isin(extant_eff_nodes), 'Eff'] = 0

        # To check the the values for each node after the earthquake event
        # Complete connectivity loss
        ccl_table['CNS'] = [
            1 if any(nx.has_path(G, j, i) for j in extant_source_nodes) else 0
            for i in extant_demand_nodes]

        # Partial Connectivity Loss
        pcl_table.loc[extant_demand_nodes, 'NS'] = [
            sum(nx.has_path(G, j, i) for j in extant_source_nodes)
            for i in extant_demand_nodes]

        wcl_table = calc_weighted_connectivity_loss(
            G, att, extant_source_nodes, extant_demand_nodes, wcl_table,
            pcl_table, 'WS', 'NS')

        eff_table = calc_efficiency(G, N, att, eff_table, 'Eff')

        # Connectivity Loss for each node
        pcl_table['PCL_node'] = 1 - (pcl_table['NS']/pcl_table['NS0'])
        wcl_table['WCL_node'] = 1 - (wcl_table['WS']/wcl_table['WS0'])

        # Computing the mean of the connectivity loss to consider the overall
        # performance of the area (at global level)
        CCL_per_event = 1 - ((ccl_table['CNS'].sum())/ccl_table['CNO'].sum())
        PCL_mean_per_event = pcl_table['PCL_node'].mean()
        WCL_mean_per_event = wcl_table['WCL_node'].mean()
        Glo_eff0_per_event = eff_table['Eff0'].mean()
        Glo_eff_per_event = eff_table['Eff'].mean()
        # Calculation of Efficiency loss
        Glo_effloss_per_event = (
            Glo_eff0_per_event - Glo_eff_per_event)/Glo_eff0_per_event

        # Storing the value of performance indicators for each event
        event_connectivity_loss_ccl = event_connectivity_loss_ccl.append(
            {'event_id': event_id, 'CCL': CCL_per_event}, ignore_index=True)
        event_connectivity_loss_pcl = event_connectivity_loss_pcl.append(
            {'event_id': event_id, 'PCL': PCL_mean_per_event},
            ignore_index=True)
        event_connectivity_loss_wcl = event_connectivity_loss_wcl.append(
            {'event_id': event_id, 'WCL': WCL_mean_per_event},
            ignore_index=True)
        event_connectivity_loss_eff = event_connectivity_loss_eff.append(
            {'event_id': event_id, 'EL': Glo_effloss_per_event},
            ignore_index=True)

        # To store the sum of performance indicator at nodal level to calulate
        # the average afterwards
        ccl_table['CCL_node'] = 1 - ccl_table['CNS']
        ccl_table1 = ccl_table.drop(columns=['CNO', 'CNS'])
        ccl_table1 = ccl_table1.reset_index()
        dem_cl = pd.concat((dem_cl, ccl_table1)).groupby(
            'id', as_index=False).sum()

        pcl_table1 = pcl_table.drop(columns=['NS0', 'NS'])
        pcl_table1 = pcl_table1.reset_index()
        dem_cl = pd.concat((dem_cl, pcl_table1)).groupby(
            'id', as_index=False).sum()

        wcl_table1 = wcl_table.drop(columns=['WS0', 'WS'])
        wcl_table1 = wcl_table1.reset_index()
        dem_cl = pd.concat((dem_cl, wcl_table1)).groupby(
            'id', as_index=False).sum()

        eff_table1 = eff_table.drop(columns=['Eff0', 'Eff'])
        eff_table1 = eff_table1.reset_index()
        node_el = pd.concat((node_el, eff_table1)).groupby(
            'id', as_index=False).sum()

    return (dem_cl, node_el, event_connectivity_loss_ccl,
            event_connectivity_loss_pcl, event_connectivity_loss_wcl,
            event_connectivity_loss_eff)


def ELWCLPCLloss_TAZ(exposure_df, G_original, TAZ_nodes,
                     eff_nodes, damage_df, g_type):
    # When the nodes acts as both demand and supply.
    # For example, traffic analysis zone in transportation network. This
    # calculates, efficiency loss (EL),
    # weighted connectivity loss (WCL),partial connectivity loss(PCL).
    # Simple connectivity loss (SCL) doesnt make any sense in this case.

    # To store the information of the performance indicators at connectivity
    # level
    taz_cl = exposure_df[exposure_df['purpose'] == 'TAZ'].iloc[:, 0:1]
    node_el = exposure_df[exposure_df['type'] == 'node'].iloc[:, 0:1]

    pcl_table = pd.DataFrame({'id': TAZ_nodes})
    wcl_table = pd.DataFrame({'id': TAZ_nodes})
    eff_table = pd.DataFrame({'id': eff_nodes})
    eff_table.set_index("id", inplace=True)
    pcl_table.set_index('id', inplace=True)
    wcl_table.set_index('id', inplace=True)

    # Create an empty dataframe with columns "event_id" and
    # "CCL"/"PCL"/"WCL"/"EL"
    event_connectivity_loss_pcl = pd.DataFrame(columns=['event_id', 'PCL'])
    event_connectivity_loss_wcl = pd.DataFrame(columns=['event_id', 'WCL'])
    event_connectivity_loss_eff = pd.DataFrame(columns=['event_id', 'EL'])

    # To check the the values for each node before the earthquake event

    # For calculating partial connectivity loss
    for i in TAZ_nodes:
        count = 0
        for j in TAZ_nodes:
            if i != j:
                if nx.has_path(G_original, j, i):
                    count = count + 1
        pcl_table.at[i, 'NS0'] = count

    # Code below is not giving correct answer because the path is checked from
    # a TAZ to every other TAZ
    # but this will include itself as well. in the above code it is done by
    # specifying (if i !=j)
    # pcl_table['NS0'] = [sum(nx.has_path(G_original, j, i) for j in TAZ_nodes)
    # for i in TAZ_nodes]

    att = nx.get_edge_attributes(G_original, 'weights')
    wcl_table = calc_weighted_connectivity_loss(
        G_original, att, TAZ_nodes, TAZ_nodes, wcl_table, pcl_table, 'WS0',
        'NS0')

    N = len(G_original)
    att = nx.get_edge_attributes(G_original, 'weights')
    eff_table = calc_efficiency(G_original, N, att, eff_table, 'Eff0')

    for event_id, event_damage_df in damage_df.groupby("event_id"):
        G = cleanup_graph(G_original, event_damage_df, g_type)

        # Checking if there is a path between any souce to each demand node.
        # Some demand nodes and source nodes may have been eliminated from
        # the network due to damage, so we do not need to check their
        # functionalities
        extant_TAZ_nodes = sorted(set(TAZ_nodes) & set(G.nodes))
        extant_eff_nodes = sorted(set(eff_nodes) & set(G.nodes))

        # If demand nodes are damaged itself (Example, building collapsed where
        # demand node is considered)
        pcl_table.loc[~pcl_table.index.isin(extant_TAZ_nodes), 'NS'] = 0
        wcl_table.loc[~wcl_table.index.isin(extant_TAZ_nodes), 'WS'] = 0
        eff_table.loc[~eff_table.index.isin(extant_eff_nodes), 'Eff'] = 0

        for i in extant_TAZ_nodes:
            count = 0
            for j in extant_TAZ_nodes:
                if i != j:
                    if nx.has_path(G, j, i):
                        count = count + 1
            pcl_table.at[i, 'NS'] = count

        wcl_table = calc_weighted_connectivity_loss(
            G, att, extant_TAZ_nodes, extant_TAZ_nodes, wcl_table, pcl_table,
            'WS', 'NS')

        eff_table = calc_efficiency(G, N, att, eff_table, 'Eff')

        # Connectivity Loss for each node
        pcl_table['PCL_node'] = 1 - (pcl_table['NS']/pcl_table['NS0'])
        wcl_table['WCL_node'] = 1 - (wcl_table['WS']/wcl_table['WS0'])

        # Computing the mean of the connectivity loss to consider the overall
        # performance of the area (at global level)
        PCL_mean_per_event = pcl_table['PCL_node'].mean()
        WCL_mean_per_event = wcl_table['WCL_node'].mean()
        Glo_eff0_per_event = eff_table['Eff0'].mean()
        Glo_eff_per_event = eff_table['Eff'].mean()
        Glo_effloss_per_event = (
            Glo_eff0_per_event - Glo_eff_per_event)/Glo_eff0_per_event

        # Storing the value of performance indicators for each event
        event_connectivity_loss_pcl = event_connectivity_loss_pcl.append(
            {'event_id': event_id, 'PCL': PCL_mean_per_event},
            ignore_index=True)
        event_connectivity_loss_wcl = event_connectivity_loss_wcl.append(
            {'event_id': event_id, 'WCL': WCL_mean_per_event},
            ignore_index=True)
        event_connectivity_loss_eff = event_connectivity_loss_eff.append(
            {'event_id': event_id, 'EL': Glo_effloss_per_event},
            ignore_index=True)

        # To store the sum of performance indicator at nodal level to calulate
        # the average afterwards
        pcl_table1 = pcl_table.drop(columns=['NS0', 'NS'])
        pcl_table1 = pcl_table1.reset_index()
        taz_cl = pd.concat(
            (taz_cl, pcl_table1)).groupby('id', as_index=False).sum()

        wcl_table1 = wcl_table.drop(columns=['WS0', 'WS'])
        wcl_table1 = wcl_table1.reset_index()
        taz_cl = pd.concat(
            (taz_cl, wcl_table1)).groupby('id', as_index=False).sum()

        eff_table1 = eff_table.drop(columns=['Eff0', 'Eff'])
        eff_table1 = eff_table1.reset_index()
        node_el = pd.concat(
            (node_el, eff_table1)).groupby('id', as_index=False).sum()

    return (taz_cl, node_el, event_connectivity_loss_pcl,
            event_connectivity_loss_wcl, event_connectivity_loss_eff)


def EL_node(exposure_df, G_original, eff_nodes, damage_df, g_type):
    # when no information about supply or demand is given or known,
    # only efficiency loss is calculated for all nodes

    # To store the information of the performance indicators at connectivity
    # level
    node_el = exposure_df[exposure_df['type'] == 'node'].iloc[:, 0:1]

    eff_table = pd.DataFrame({'id': eff_nodes})
    eff_table.set_index("id", inplace=True)

    # Create an empty dataframe with columns "event_id" and "EL"
    event_connectivity_loss_eff = pd.DataFrame(columns=['event_id', 'EL'])

    # To check the the values for each node before the earthquake event

    N = len(G_original)
    att = nx.get_edge_attributes(G_original, 'weights')
    eff_table = calc_efficiency(G_original, N, att, eff_table, 'Eff0')

    # After eathquake
    for event_id, event_damage_df in damage_df.groupby("event_id"):
        G = cleanup_graph(G_original, event_damage_df, g_type)

        # Checking if there is a path between any souce to each demand node.
        # Some demand nodes and source nodes may have been eliminated from
        # the network due to damage, so we do not need to check their
        # functionalities
        extant_eff_nodes = sorted(set(eff_nodes) & set(G.nodes))

        # If demand nodes are damaged itself (Example, building collapsed where
        # demand node is considered)
        eff_table.loc[~eff_table.index.isin(extant_eff_nodes), 'Eff'] = 0

        # To check the the values for each node after the earthquake event
        eff_table = calc_efficiency(G, N, att, eff_table, 'Eff')

        # Computing the mean of the connectivity loss to consider the overall
        # performance of the area (at global level)
        Glo_eff0_per_event = eff_table['Eff0'].mean()
        Glo_eff_per_event = eff_table['Eff'].mean()
        Glo_effloss_per_event = (
            Glo_eff0_per_event - Glo_eff_per_event)/Glo_eff0_per_event

        # Storing the value of performance indicators for each event
        event_connectivity_loss_eff = event_connectivity_loss_eff.append(
            {'event_id': event_id, 'EL': Glo_effloss_per_event},
            ignore_index=True)

        # To store the sum of performance indicator at nodal level to calulate
        # the average afterwards
        eff_table1 = eff_table.drop(columns=['Eff0', 'Eff'])
        eff_table1 = eff_table1.reset_index()
        node_el = pd.concat(
            (node_el, eff_table1)).groupby('id', as_index=False).sum()

    return node_el, event_connectivity_loss_eff
