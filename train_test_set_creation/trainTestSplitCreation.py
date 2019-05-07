import math
import os
import random

import numpy
import pandas

import graph_creation.graphCreationConfig as glob
import graph_creation.utils as utils

RANDOM_STATE = 42  # do not change for reproducibility
random.seed(RANDOM_STATE)
numpy.random.seed(RANDOM_STATE)
COL_NAMES_EDGES = ['id1', 'edgeType', 'id2', 'qscore']
COL_NAMES_SAMPLES = ['id1', 'edgeType', 'id2', 'qscore', 'value']


# TODO: random per edgeType (equally dist vs original dist)
# TODO: no self loops in neg samples, not reproducible(?)

# (sub)sample negative examples
# only provided TN
# provided + equally distributed
# original distribution + providing (some) tn ?


class TrainTestSetCreation():
    def __init__(self, graph_path, tn_graph_path, nodes_path, meta_edge_triples=None):

        with open(nodes_path) as file:
            self.nodes = pandas.read_csv(file, sep='\t', names=['id', 'nodeType'])

        with open(graph_path) as file:
            self.all_tp = pandas.read_csv(file, sep='\t', names=COL_NAMES_EDGES)
            self.all_tp['value'] = 1
        self.tp_edgeTypes = list(self.all_tp['edgeType'].unique())

        with open(tn_graph_path) as file:
            self.all_tn = pandas.read_csv(file, sep='\t', names=COL_NAMES_EDGES)
            self.all_tn['value'] = 0
        self.tn_edgeTypes = list(self.all_tn['edgeType'].unique())

        self.meta_edges_dic = {}
        if not meta_edge_triples:
            import graph_creation.metadata_edge.edgeMetadata as meta
            for metaEdge in utils.get_leaf_subclasses(meta.EdgeMetadata):
                edgeType =  str(metaEdge.EDGE_INMETA_CLASS.EDGE_TYPE)
                node1Type = str(metaEdge.EDGE_INMETA_CLASS.NODE1_TYPE)
                node2Type = str(metaEdge.EDGE_INMETA_CLASS.NODE2_TYPE)
                if edgeType in self.tp_edgeTypes:
                    self.meta_edges_dic['%s_%s_%s'%(node1Type,edgeType,node2Type)] = (node1Type, edgeType, node2Type)
        else:
            for node1Type, edgeType, node2Type in meta_edge_triples:
                self.meta_edges_dic['%s_%s_%s' % (node1Type, edgeType, node2Type)] = (node1Type, edgeType, node2Type)

        # check for transient onto edges
        transitiv_IS_A_edges = self.check_for_transitive_edges(self.all_tp[self.all_tp['edgeType'] == 'IS_A'])
        transitiv_PART_OF_edges = self.check_for_transitive_edges(self.all_tp[self.all_tp['edgeType'] == 'PART_OF'])
        if transitiv_IS_A_edges:
            print('WARNING: transient edges in IS_A: ({a},b,c) for a IS_A b and a IS_A c', transitiv_IS_A_edges)
        if transitiv_PART_OF_edges:
            print('WARNING: transient edges in PART_OF: ({a},b,c) for a PART_OF b and a PART_OF c',
                  transitiv_PART_OF_edges)

    def random_edge_split(self, val_frac=None, test_frac=None, crossval=None, folds=None):  # todo change to list of graph and tn graph files
        if not val_frac:
            val_frac = 0.2
        if not test_frac:
            test_frac = 0.2

        # create positive and negative examples
        positive_samples = self.all_tp
        negative_samples = self.generate_negative_samples(positive_samples)
        all_samples = (positive_samples.append(negative_samples, ignore_index=True)).reset_index(drop=True)

        # generate, train-, test-, validation-sets
        test_set = all_samples.sample(frac=test_frac, random_state=RANDOM_STATE)
        train_val_set = all_samples.drop(list(test_set.index.values))
        if glob.DIRECTED:
            train_val_set = self.remove_bidir_edges(remain_set=train_val_set, remove_set=test_set)
        if crossval:
            if folds:
                train_val_set_tuples = self.create_cross_val(train_val_set, folds)
            else:
                train_val_set_tuples = self.create_cross_val(train_val_set, val_frac)
        else:
            train_set = train_val_set.sample(frac=(1 - val_frac), random_state=RANDOM_STATE)
            val_set = train_val_set.drop(list(train_set.index.values))
            train_val_set_tuples = [(train_set, val_set)]
        if glob.DIRECTED:
            train_val_set_tuples = [(self.remove_bidir_edges(remain_set=t, remove_set=v),v) for t,v in train_val_set_tuples]

        self.print_sets(train_val_set_tuples,test_set)
        return (train_val_set_tuples, test_set)


    def generate_negative_samples(self, positive_samples):
        negative_samples = pandas.DataFrame(columns=list(positive_samples))

        # generate random distribution of meta_edge types for negative samples
        num_tp_examples, _ = positive_samples.shape
        meta_edges = list(self.meta_edges_dic.keys())
        meta_edges.sort()
        negative_samples_metaEdges = (list(numpy.random.choice(meta_edges, num_tp_examples)))
        negative_samples_metaEdges.sort()
        negative_samples_count_metaEdges = {e: negative_samples_metaEdges.count(e) for e in
                                            set(negative_samples_metaEdges)}

        # generate a negative sub-sample for each negative meta_edge type
        for meta_edge_triple_key, count in sorted(negative_samples_count_metaEdges.items()):
            meta_node1, meta_edge, meta_node2 = self.meta_edges_dic[meta_edge_triple_key]
            exclude_df = positive_samples.loc[(positive_samples['id1'].str.startswith(meta_node1)) &
                                              (positive_samples['edgeType'] == meta_edge)&
                                              (positive_samples['id2'].str.startswith(meta_node2))]
            #exclude_df = exclude_df.append(negative_samples,ignore_index=True)
            if meta_edge in self.tn_edgeTypes: #only onto edgesTypes can appear multiple times, there should be no onto tn
                negative_samples = self.subsample_with_tn(meta_edge_triple_key=meta_edge_triple_key,
                                                          count=count,
                                                          negative_samples=negative_samples,
                                                          exclude_df=exclude_df)
            else:
                negative_samples = negative_samples.append(self.generate_n_random_samples(n=count,
                                                                                          meta_edge_triple_key=meta_edge_triple_key,
                                                                                          exclude_df=exclude_df)
                                                           , ignore_index=True)
        negative_samples['value'] = 0

        return negative_samples


    def subsample_with_tn(self, meta_edge_triple_key, count, negative_samples, exclude_df):
        nodeType1, edgeType, nodeType2 = self.meta_edges_dic[meta_edge_triple_key]
        tn_examples = self.all_tn.loc[(self.all_tn['id1'].str.startswith(nodeType1)) &
                                              (self.all_tn['edgeType'] == edgeType)&
                                              (self.all_tn['id2'].str.startswith(nodeType2))]
        count_existing_tn, _ = tn_examples.shape
        if count <= count_existing_tn:
            random_tn_sample = tn_examples.sample(n=count, random_state=RANDOM_STATE)
            negative_samples = negative_samples.append(random_tn_sample, ignore_index=True)
        else:
            random_tn_sample = tn_examples.sample(n=count_existing_tn, random_state=RANDOM_STATE)
            exclude_df = exclude_df.append(random_tn_sample)
            negative_samples = negative_samples.append(random_tn_sample, ignore_index=True)
            negative_samples = negative_samples.append(
                self.generate_n_random_samples(n=(count - count_existing_tn),
                                               meta_edge_triple_key=meta_edge_triple_key,
                                               exclude_df=exclude_df)
                , ignore_index=True)
        return negative_samples


    def check_for_transitive_edges(self, df):
        direct_child_dict={}
        for row in df[['id1', 'id2']].itertuples():
            _, child, parent = row
            if not parent in direct_child_dict.keys():
                direct_child_dict[parent] = {child}
            else:
                direct_child_dict[parent].add(child)
        #fixme check for cycles
        all_children =set()
        return ([((child_set & direct_child_dict[c]), parent, c)  for (parent, child_set) in direct_child_dict.items() for c in child_set if c in direct_child_dict.keys() if (child_set & direct_child_dict[c])])

    #def get_all_childs(self,direct_child_dict, current_parent, past_parents, all_children):
    #    for child in direct_child_dict[current_parent]:
    #        pass
            #fixme continue here (more lvl transitivity

          

    def remove_bidir_edges(self,remain_set, remove_set):
        remove_set_copy = remove_set.copy()
        cols_other_dir = list(remove_set_copy.columns)
        index_id1 = cols_other_dir.index('id1')
        index_id2 = cols_other_dir.index('id2')
        cols_other_dir[index_id1]= 'id2'
        cols_other_dir[index_id2]= 'id1'
        remove_set_copy.columns = cols_other_dir
        temp = pandas.merge(remain_set, remove_set_copy, how='left', left_on=['id1', 'id2', 'edgeType'],
                            right_on=['id1', 'id2', 'edgeType']).set_index(remain_set.index)
        # todo value should always be different? are there examples with diff qscore?
        remove = temp[(temp['value_x'] == temp['value_y'])]
        remain = remain_set.drop(remove.index.values)
        return remain


    def create_cross_val(self, df, n_folds):
        nel_total, _ = df.shape
        if n_folds < 1: #n_folds is fraction
            n_folds = math.ceil(1/n_folds)
        nel_per_chunk = math.ceil(nel_total / n_folds)
        rand_index = list(df.index.values)
        random.shuffle(rand_index)

        bounds = []
        for i in range(n_folds):
            bounds.append(i * nel_per_chunk)
        bounds.append(nel_total)

        chunks = []
        for i in range(n_folds):
            chunks.append(rand_index[bounds[i]: bounds[i + 1]])

        folds_indices = []
        for i in range(n_folds):
            train_chunk_indices = [(x + i) % n_folds for x in range(n_folds - 1)]
            val_chunk_index = (n_folds - 1 + i) % n_folds
            train_indices = [element for chunk_index in train_chunk_indices for element in chunks[chunk_index]]
            val_indices = chunks[val_chunk_index]
            folds_indices.append((train_indices, val_indices))

        folds = []
        for train_indices, val_indices in folds_indices:
            folds.append((df.loc[train_indices], df.loc[val_indices]))

        return folds


    def generate_n_random_samples(self, n, meta_edge_triple_key, exclude_df):
        nodeType1, edgeType, nodeType2 = self.meta_edges_dic[meta_edge_triple_key]
        samples = pandas.DataFrame(columns=COL_NAMES_EDGES)
        nodes_nodeType1 = self.nodes.loc[self.nodes['nodeType'] == nodeType1]
        num_nodes1, _ = nodes_nodeType1.shape
        nodes_nodeType2 = self.nodes.loc[self.nodes['nodeType'] == nodeType2]
        num_nodes2, _ = nodes_nodeType2.shape

        i = 0
        while True:
            node1 = nodes_nodeType1.sample(n=1, random_state=(RANDOM_STATE+i))
            node1.reset_index()
            node2 = nodes_nodeType2.sample(n=1, random_state=(RANDOM_STATE+((i+100)%13)))
            node2.reset_index()
            if not (((exclude_df['id1'] == node1.iloc[0].id) &
                     (exclude_df['id2'] == node2.iloc[0].id) &
                     (exclude_df['edgeType'] == edgeType)).any() or
                    (node1.iloc[0].id == node2.iloc[0].id)):  # no self loops
                samples = samples.append(pandas.DataFrame([[node1.iloc[0].id, edgeType, node2.iloc[0].id, 0]],
                                                          columns=COL_NAMES_EDGES),
                                         ignore_index=True)
                exclude_df = exclude_df.append(pandas.DataFrame([[node1.iloc[0].id, edgeType, node2.iloc[0].id, 0]],
                                                                columns=COL_NAMES_EDGES),
                                               ignore_index=True)
                num_samples, _ = samples.shape
                if num_samples >= n:
                    break
            i += 1
            if i >= num_nodes1 * num_nodes2:
                # fixme throw error not enough samples could be genereated from set
                break
        return samples


    def print_sets(self, train_val_set_tuples, test_set):
        # todo not here
        crossval_dir = os.path.join(os.getcwd(), "cross_val")
        i = 0
        for train_set, val_set in train_val_set_tuples:
            folder_path = os.path.join(crossval_dir, "fold_%d" % (i))
            os.makedirs(folder_path, exist_ok=True)
            train_set[COL_NAMES_SAMPLES].to_csv(os.path.join(folder_path, "train_sample.csv"),
                                                sep='\t',
                                                index=False,
                                                header=False)
            val_set[COL_NAMES_SAMPLES].to_csv(os.path.join(folder_path, "val_sample.csv"),
                                              sep='\t',
                                              index=False,
                                              header=False)
            i+=1
        test_set[COL_NAMES_SAMPLES].to_csv(os.path.join(crossval_dir, "train_sample.csv"),
                                           sep='\t',
                                           index=False,
                                           header=False)







