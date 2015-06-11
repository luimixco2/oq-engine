# Copyright (c) 2010-2015, GEM Foundation.
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake.  If not, see <http://www.gnu.org/licenses/>.

import time
import logging
import operator
import itertools
import collections
import random
from lxml import etree

import numpy

from openquake.baselib.general import AccumDict, groupby
from openquake.commonlib.node import read_nodes
from openquake.commonlib import valid, logictree, sourceconverter, parallel
from openquake.commonlib.nrml import nodefactory, PARSE_NS_MAP


class DuplicatedID(Exception):
    """Raised when two sources with the same ID are found in a source model"""


class LtRealization(object):
    """
    Composite realization build on top of a source model realization and
    a GSIM realization.
    """
    def __init__(self, ordinal, sm_lt_path, gsim_rlz, weight, col_ids=()):
        self.ordinal = ordinal
        self.sm_lt_path = sm_lt_path
        self.gsim_rlz = gsim_rlz
        self.weight = weight
        self.col_ids = col_ids

    def __repr__(self):
        if self.col_ids:
            col = ',col=' + ','.join(map(str, sorted(self.col_ids)))
        else:
            col = ''
        return '<%d,%s,w=%s%s>' % (self.ordinal, self.uid, self.weight, col)

    @property
    def gsim_lt_path(self):
        return self.gsim_rlz.lt_path

    @property
    def uid(self):
        """An unique identifier for effective realizations"""
        return '_'.join(self.sm_lt_path) + ',' + self.gsim_rlz.uid

    def __eq__(self, other):
        return repr(self) == repr(other)

    def __ne__(self, other):
        return repr(self) != repr(other)

    def __hash__(self):
        return hash(repr(self))


def get_skeleton(sm):
    """
    Return a copy of the source model `sm` which is empty, i.e. without
    sources.
    """
    trt_models = [TrtModel(tm.trt, [], tm.num_ruptures, tm.min_mag,
                           tm.max_mag, tm.gsims, tm.id)
                  for tm in sm.trt_models]
    return SourceModel(sm.name, sm.weight, sm.path, trt_models, sm.gsim_lt,
                       sm.ordinal, sm.samples)

SourceModel = collections.namedtuple(
    'SourceModel', 'name weight path trt_models gsim_lt ordinal samples')


def get_weight(src, point_source_weight=1/40., num_ruptures=None):
    """
    :param src: a hazardlib source object
    :param point_source_weight: default 1/40
    :param num_ruptures: if None it is recomputed
    :returns: the weight of the given source
    """
    num_ruptures = num_ruptures or src.count_ruptures()
    weight = (num_ruptures * point_source_weight
              if src.__class__.__name__ == 'PointSource'
              else num_ruptures)
    return weight


class TrtModel(collections.Sequence):
    """
    A container for the following parameters:

    :param str trt:
        the tectonic region type all the sources belong to
    :param list sources:
        a list of hazardlib source objects
    :param int num_ruptures:
        the total number of ruptures generated by the given sources
    :param min_mag:
        the minimum magnitude among the given sources
    :param max_mag:
        the maximum magnitude among the given sources
    :param gsims:
        the GSIMs associated to tectonic region type
    :param id:
        an optional numeric ID (default None) useful to associate
        the model to a database object
    """
    POINT_SOURCE_WEIGHT = 1 / 40.

    @classmethod
    def collect(cls, sources):
        """
        :param sources: dictionaries with a key 'tectonicRegion'
        :returns: an ordered list of TrtModel instances
        """
        source_stats_dict = {}
        for src in sources:
            trt = src['tectonicRegion']
            if trt not in source_stats_dict:
                source_stats_dict[trt] = TrtModel(trt)
            tm = source_stats_dict[trt]
            if not tm.sources:

                # we increate the rupture counter by 1,
                # to avoid filtering away the TRTModel
                tm.num_ruptures = 1

                # we append just one source per TRTModel, so that
                # the memory occupation is insignificand and at
                # the same time we avoid the RuntimeError
                # "All sources were filtered away"
                tm.sources.append(src)

        # return TrtModels, ordered by TRT string
        return sorted(source_stats_dict.itervalues())

    def __init__(self, trt, sources=None, num_ruptures=0,
                 min_mag=None, max_mag=None, gsims=None, id=0):
        self.trt = trt
        self.sources = sources or []
        self.num_ruptures = num_ruptures
        self.min_mag = min_mag
        self.max_mag = max_mag
        self.gsims = gsims or []
        self.id = id
        for src in self.sources:
            self.update(src)

    def update(self, src):
        """
        Update the attributes sources, min_mag, max_mag
        according to the given source.

        :param src:
            an instance of :class:
            `openquake.hazardlib.source.base.BaseSeismicSource`
        """
        assert src.tectonic_region_type == self.trt, (
            src.tectonic_region_type, self.trt)
        self.sources.append(src)
        min_mag, max_mag = src.get_min_max_mag()
        prev_min_mag = self.min_mag
        if prev_min_mag is None or min_mag < prev_min_mag:
            self.min_mag = min_mag
        prev_max_mag = self.max_mag
        if prev_max_mag is None or max_mag > prev_max_mag:
            self.max_mag = max_mag

    def __repr__(self):
        return '<%s #%d %s, %d source(s), %d rupture(s)>' % (
            self.__class__.__name__, self.id, self.trt,
            len(self.sources), self.num_ruptures)

    def __lt__(self, other):
        """
        Make sure there is a precise ordering of TrtModel objects.
        Objects with less sources are put first; in case the number
        of sources is the same, use lexicographic ordering on the trts
        """
        num_sources = len(self.sources)
        other_sources = len(other.sources)
        if num_sources == other_sources:
            return self.trt < other.trt
        return num_sources < other_sources

    def __getitem__(self, i):
        return self.sources[i]

    def __iter__(self):
        return iter(self.sources)

    def __len__(self):
        return len(self.sources)


def parse_source_model(fname, converter, apply_uncertainties=lambda src: None):
    """
    Parse a NRML source model and return an ordered list of TrtModel
    instances.

    :param str fname:
        the full pathname of the source model file
    :param converter:
        :class:`openquake.commonlib.source.SourceConverter` instance
    :param apply_uncertainties:
        a function modifying the sources (or do nothing)
    """
    converter.fname = fname
    source_stats_dict = {}
    source_ids = set()
    src_nodes = read_nodes(fname, lambda elem: 'Source' in elem.tag,
                           nodefactory['sourceModel'])
    for no, src_node in enumerate(src_nodes, 1):
        src = converter.convert_node(src_node)
        if src.source_id in source_ids:
            raise DuplicatedID(
                'The source ID %s is duplicated!' % src.source_id)
        apply_uncertainties(src)
        trt = src.tectonic_region_type
        if trt not in source_stats_dict:
            source_stats_dict[trt] = TrtModel(trt)
        source_stats_dict[trt].update(src)
        source_ids.add(src.source_id)
        if no % 10000 == 0:  # log every 10,000 sources parsed
            logging.info('Parsed %d sources from %s', no, fname)

    # return ordered TrtModels
    return sorted(source_stats_dict.itervalues())


def agg_prob(acc, prob):
    """Aggregation function for probabilities"""
    return 1. - (1. - acc) * (1. - prob)


def get_col_id(tag):
    """
    Extract the ses collection index from the tag:

    >>> get_col_id('col=01|...')
    1
    """
    return int(tag.split('|', 1)[0].split('=')[1])


class RlzsAssoc(collections.Mapping):
    """
    Realization association class. It should not be instantiated directly,
    but only via the method :meth:
    `openquake.commonlib.source.CompositeSourceModel.get_rlzs_assoc`.

    :attr realizations: list of LtRealization objects
    :attr gsim_by_trt: list of dictionaries {trt: gsim}
    :attr rlzs_assoc: dictionary {trt_model_id, gsim: rlzs}
    :attr rlzs_by_smodel: dictionary {source_model_ordinal: rlzs}

    For instance, for the non-trivial logic tree in
    :mod:`openquake.qa_tests_data.classical.case_15`, which has 4 tectonic
    region types and 4 + 2 + 2 realizations, there are the following
    associations:

    (0, 'BooreAtkinson2008') ['#0-SM1-BA2008_C2003', '#1-SM1-BA2008_T2002']
    (0, 'CampbellBozorgnia2008') ['#2-SM1-CB2008_C2003', '#3-SM1-CB2008_T2002']
    (1, 'Campbell2003') ['#0-SM1-BA2008_C2003', '#2-SM1-CB2008_C2003']
    (1, 'ToroEtAl2002') ['#1-SM1-BA2008_T2002', '#3-SM1-CB2008_T2002']
    (2, 'BooreAtkinson2008') ['#4-SM2_a3pt2b0pt8-BA2008']
    (2, 'CampbellBozorgnia2008') ['#5-SM2_a3pt2b0pt8-CB2008']
    (3, 'BooreAtkinson2008') ['#6-SM2_a3b1-BA2008']
    (3, 'CampbellBozorgnia2008') ['#7-SM2_a3b1-CB2008']
    """
    def __init__(self, csm_info, rlzs_assoc=None):
        self.csm_info = csm_info
        self.rlzs_assoc = rlzs_assoc or collections.defaultdict(list)
        self.gsim_by_trt = []  # rlz.ordinal -> {trt: gsim}
        self.rlzs_by_smodel = collections.OrderedDict()

    @property
    def realizations(self):
        """Flat list with all the realizations"""
        return sum(self.rlzs_by_smodel.itervalues(), [])

    def get_gsims_by_trt_id(self):
        """Returns associations trt_id -> [GSIM instance, ...]"""
        return groupby(
            self.rlzs_assoc, operator.itemgetter(0),
            lambda group: sorted(valid.gsim(gsim)
                                 for trt_id, gsim in group))

    def get_gsims_by_col(self):
        """Return a list of lists of GSIMs of length num_collections"""
        gsims = self.get_gsims_by_trt_id()
        return [gsims.get(self.csm_info.get_trt_id(col), [])
                for col in range(self.csm_info.num_collections)]

    def _add_realizations(self, idx, lt_model, realizations):
        gsim_lt = lt_model.gsim_lt
        rlzs = []
        for i, gsim_rlz in enumerate(realizations):
            weight = float(lt_model.weight) * float(gsim_rlz.weight)
            rlz = LtRealization(idx, lt_model.path, gsim_rlz, weight, set())
            self.gsim_by_trt.append(dict(
                zip(gsim_lt.all_trts, gsim_rlz.value)))
            for trt_model in lt_model.trt_models:
                trt = trt_model.trt
                gsim = gsim_lt.get_gsim_by_trt(gsim_rlz, trt)
                self.rlzs_assoc[trt_model.id, gsim].append(rlz)
                trt_model.gsims = gsim_lt.values[trt]
                if lt_model.samples > 1:  # oversampling
                    col_id = self.csm_info.get_col_id(trt_model.id, i)
                    rlz.col_ids.add(col_id)
            idx += 1
            rlzs.append(rlz)
        self.rlzs_by_smodel[lt_model.ordinal] = rlzs
        return idx

    def combine_curves(self, results, agg, acc):
        """
        :param results: dictionary (trt_model_id, gsim_name) -> curves
        :param agg: aggregation function (composition of probabilities)
        :returns: a dictionary rlz -> aggregated curves
        """
        ad = AccumDict({rlz: acc for rlz in self.realizations})
        for key, value in results.iteritems():
            for rlz in self.rlzs_assoc[key]:
                ad[rlz] = agg(ad[rlz], value)
        return ad

    def combine_gmfs(self, results):
        """
        :param results: a dictionary (trt_model_id, gsim_name) -> gmf_by_tag
        """
        ad = {rlz: AccumDict() for rlz in self.realizations}
        for key, gmf_by_tag in results.iteritems():
            for rlz in self.rlzs_assoc[key]:
                if not rlz.col_ids:
                    ad[rlz] += gmf_by_tag
                else:
                    for tag in gmf_by_tag:
                        # if the rupture contributes to the given realization
                        if get_col_id(tag) in rlz.col_ids:
                            ad[rlz][tag] = gmf_by_tag[tag]
        return ad

    def combine(self, results, agg=agg_prob):
        """
        :param results: a dictionary (trt_model_id, gsim_name) -> floats
        :param agg: an aggregation function
        :returns: a dictionary rlz -> aggregated floats

        Example: a case with tectonic region type T1 with GSIMS A, B, C
        and tectonic region type T2 with GSIMS D, E.

        >>> assoc = RlzsAssoc(CompositionInfo([]), {
        ... ('T1', 'A'): ['r0', 'r1'],
        ... ('T1', 'B'): ['r2', 'r3'],
        ... ('T1', 'C'): ['r4', 'r5'],
        ... ('T2', 'D'): ['r0', 'r2', 'r4'],
        ... ('T2', 'E'): ['r1', 'r3', 'r5']})
        ...
        >>> results = {
        ... ('T1', 'A'): 0.01,
        ... ('T1', 'B'): 0.02,
        ... ('T1', 'C'): 0.03,
        ... ('T2', 'D'): 0.04,
        ... ('T2', 'E'): 0.05,}
        ...
        >>> combinations = assoc.combine(results, operator.add)
        >>> for key, value in sorted(combinations.items()): print key, value
        r0 0.05
        r1 0.06
        r2 0.06
        r3 0.07
        r4 0.07
        r5 0.08

        You can check that all the possible sums are performed:

        r0: 0.01 + 0.04 (T1A + T2D)
        r1: 0.01 + 0.05 (T1A + T2E)
        r2: 0.02 + 0.04 (T1B + T2D)
        r3: 0.02 + 0.05 (T1B + T2E)
        r4: 0.03 + 0.04 (T1C + T2D)
        r5: 0.03 + 0.05 (T1C + T2E)

        In reality, the `combine_curves` method is used with hazard_curves and
        the aggregation function is the `agg_curves` function, a composition of
        probability, which however is close to the sum for small probabilities.
        """
        ad = AccumDict()
        for key, value in results.iteritems():
            for rlz in self.rlzs_assoc[key]:
                ad[rlz] = agg(ad.get(rlz, 0), value)
        return ad

    def __iter__(self):
        return self.rlzs_assoc.iterkeys()

    def __getitem__(self, key):
        return self.rlzs_assoc[key]

    def __len__(self):
        return len(self.rlzs_assoc)

    def __repr__(self):
        pairs = []
        for key in sorted(self.rlzs_assoc):
            rlzs = map(str, self.rlzs_assoc[key])
            if len(rlzs) > 10:  # short representation
                rlzs = ['%d realizations' % len(rlzs)]
            pairs.append(('%s,%s' % key, rlzs))
        return '<%s\n%s>' % (self.__class__.__name__,
                             '\n'.join('%s: %s' % pair for pair in pairs))


class CompositionInfo(object):
    """
    An object to collect information about the composition of
    a composite source model.
    """
    def __init__(self, source_models):
        self._col_dict = {}  # dictionary trt_id, idx -> col_id
        self._num_samples = {}  # trt_id -> num_samples
        self.source_models = map(get_skeleton, source_models)
        col_id = 0
        for sm in source_models:
            for trt_model in sm.trt_models:
                trt_id = trt_model.id
                if sm.samples > 1:
                    self._num_samples[trt_id] = sm.samples
                for idx in range(sm.samples):
                    self._col_dict[trt_id, idx] = col_id
                    col_id += 1
                trt_id += 1
        self.num_collections = col_id

    def get_max_samples(self):
        """Return the maximum number of samples of the source model"""
        values = self._num_samples.values()
        if not values:
            return 1
        return max(values)

    def get_num_samples(self, trt_id):
        """
        :param trt_id: tectonic region type object ID
        :returns: how many times the sources of that TRT are to be sampled
        """
        return self._num_samples.get(trt_id, 1)

    # this useful to extract the ruptures affecting a given realization
    def get_col_ids(self, rlz):
        """
        :param rlz: a realization
        :returns: a set of ses collection indices relevant for the realization
        """
        # first consider the oversampling case, when the col_ids are known
        if rlz.col_ids:
            return rlz.col_ids
        # else consider the source model to which the realization belongs
        # and extract the trt_model_ids, which are the same as the col_ids
        return set(tm.id for sm in self.source_models
                   for tm in sm.trt_models if sm.path == rlz.sm_lt_path)

    def get_col_id(self, trt_id, idx):
        """
        :param trt_id: tectonic region type object ID
        :param idx: an integer index from 0 to num_samples
        :returns: the SESCollection ordinal
        """
        return self._col_dict[trt_id, idx]

    def get_trt_id(self, col_id):
        """
        :param col_id: the ordinal of a SESCollection
        :returns: the ID of the associated TrtModel
        """
        for (trt_id, idx), cid in self._col_dict.iteritems():
            if cid == col_id:
                return trt_id
        raise KeyError('There is no TrtModel associated to the collection %d!'
                       % col_id)

    def get_triples(self):
        """
        Yield triples (trt_id, idx, col_id) in order
        """
        for (trt_id, idx), col_id in sorted(self._col_dict.iteritems()):
            yield trt_id, idx, col_id

    def __repr__(self):
        info_by_model = collections.OrderedDict(
            (sm.path, ('_'.join(sm.path), sm.name,
                       [tm.id for tm in sm.trt_models],
                       sm.gsim_lt.get_num_paths() * sm.samples))
            for sm in self.source_models)
        summary = ['%s, %s, trt=%s: %d realization(s)' % ibm
                   for ibm in info_by_model.itervalues()]
        return '<%s\n%s>' % (
            self.__class__.__name__, '\n'.join(summary))


class CompositeSourceModel(collections.Sequence):
    """
    :param source_model_lt:
        a :class:`openquake.commonlib.logictree.SourceModelLogicTree` instance
    :param source_models:
        a list of :class:`openquake.commonlib.source.SourceModel` tuples
    """
    def __init__(self, source_model_lt, source_models):
        self.source_model_lt = source_model_lt
        self.source_models = list(source_models)
        self.info = CompositionInfo(source_models)
        self.source_info = ()  # set by the SourceProcessor

    @property
    def trt_models(self):
        """
        Yields the TrtModels inside each source model.
        """
        for sm in self.source_models:
            for trt_model in sm.trt_models:
                yield trt_model

    def get_sources(self):
        """
        Extract the sources contained in the internal source models.
        """
        sources = []
        for trt_model in self.trt_models:
            for src in trt_model:
                if hasattr(src, 'trt_model_id'):
                    # .trt_model_id is missing for source nodes
                    src.trt_model_id = trt_model.id
                sources.append(src)
        return sources

    def get_num_sources(self):
        """
        :returns: the total number of sources in the model
        """
        return len(self.get_sources())

    def count_ruptures(self, really=False):
        """
        Update the attribute .num_ruptures in each TRT model.
        This method is lazy, i.e. the number is not updated if it is already
        set and nonzero, unless `really` is True.
        """
        for trt_model in self.trt_models:
            if trt_model.num_ruptures == 0 or really:
                trt_model.num_ruptures = sum(
                    src.count_ruptures() for src in trt_model)

    def get_rlzs_assoc(self, get_weight=lambda tm: tm.num_ruptures):
        """
        Return a RlzsAssoc with fields realizations, gsim_by_trt,
        rlz_idx and trt_gsims.

        :param get_weight: a function trt_model -> positive number
        """
        assoc = RlzsAssoc(self.info)
        random_seed = self.source_model_lt.seed
        num_samples = self.source_model_lt.num_samples
        idx = 0
        for smodel in self.source_models:
            # count the number of ruptures per tectonic region type
            trts = set()
            for trt_model in smodel.trt_models:
                if get_weight(trt_model) > 0:
                    trts.add(trt_model.trt)
            # recompute the GSIM logic tree if needed
            if trts != set(smodel.gsim_lt.tectonic_region_types):
                smodel.gsim_lt.reduce(trts)
            if num_samples:  # sampling
                rnd = random.Random(random_seed + idx)
                rlzs = logictree.sample(smodel.gsim_lt, smodel.samples, rnd)
            else:  # full enumeration
                rlzs = logictree.get_effective_rlzs(smodel.gsim_lt)
            if rlzs:
                idx = assoc._add_realizations(idx, smodel, rlzs)
            else:
                logging.warn('No realizations for %s, %s',
                             '_'.join(smodel.path), smodel.name)
        if assoc.realizations:
            if num_samples:
                assert len(assoc.realizations) == num_samples
                for rlz in assoc.realizations:
                    rlz.weight = 1. / num_samples
            else:
                tot_weight = sum(rlz.weight for rlz in assoc.realizations)
                if tot_weight == 0:
                    raise ValueError('All realizations have zero weight??')
                elif abs(tot_weight - 1) > 1E-12:  # allow for rounding errors
                    logging.warn('Some source models are not contributing, '
                                 'weights are being rescaled')
                for rlz in assoc.realizations:
                    rlz.weight = rlz.weight / tot_weight
        return assoc

    def __repr__(self):
        """
        Return a string representation of the composite model
        """
        models = ['%d-%s-%s,w=%s [%d trt_model(s)]' % (
            sm.ordinal, sm.name, '_'.join(sm.path), sm.weight,
            len(sm.trt_models)) for sm in self]
        return '<%s\n%s>' % (self.__class__.__name__, '\n'.join(models))

    def __getitem__(self, i):
        """Return the i-th source model"""
        return self.source_models[i]

    def __iter__(self):
        """Return an iterator over the underlying source models"""
        return iter(self.source_models)

    def __len__(self):
        """Return the number of underlying source models"""
        return len(self.source_models)


def _collect_source_model_paths(smlt):
    """
    Given a path to a source model logic tree or a file-like, collect all of
    the soft-linked path names to the source models it contains and return them
    as a uniquified list (no duplicates).
    """
    src_paths = []
    tree = etree.parse(smlt)
    for branch_set in tree.xpath('//nrml:logicTreeBranchSet',
                                 namespaces=PARSE_NS_MAP):

        if branch_set.get('uncertaintyType') == 'sourceModel':
            for branch in branch_set.xpath(
                    './nrml:logicTreeBranch/nrml:uncertaintyModel',
                    namespaces=PARSE_NS_MAP):
                src_paths.append(branch.text)
    return sorted(set(src_paths))


# ########################## SourceProcessor ############################# #

def filter_and_split(src, sourceprocessor):
    """
    Filter and split the source by using the source processor.
    Also, sets the sub sources `.weight` attribute.

    :param src: a hazardlib source object
    :param sourceprocessor: a SourceProcessor object
    :returns: a named tuple of type SourceInfo
    """
    if sourceprocessor.sitecol:  # filter
        t0 = time.time()
        sites = src.filter_sites_by_distance_to_source(
            sourceprocessor.maxdist, sourceprocessor.sitecol)
        filter_time = time.time() - t0
        if sites is None:
            return SourceInfo(src.trt_model_id, src.source_id,
                              src.__class__.__name__, [], filter_time, 0)
    else:  # only split
        filter_time = 0
    t1 = time.time()
    out = []
    for ss in sourceconverter.split_source(src, sourceprocessor.asd):
        ss.weight = get_weight(ss)
        out.append(ss)
    split_time = time.time() - t1
    return SourceInfo(src.trt_model_id, src.source_id,
                      src.__class__.__name__, out, filter_time, split_time)


SourceInfo = collections.namedtuple(
    'SourceInfo', 'trt_model_id source_id source_class sources '
    'filter_time split_time')


class SourceProcessor(object):
    """
    Filter and split in parallel the sources of the given CompositeSourceModel
    instance. An array `.source_info` is added to the instance, containing
    information about the processing times and the splitting process.

    :param sitecol: a SiteCollection instance
    :param maxdist: maximum distance for the filtering
    :param asd: area source discretization
    """

    def __init__(self, sitecol, maxdist, area_source_discretization):
        self.sitecol = sitecol
        self.maxdist = maxdist
        self.asd = area_source_discretization

    def agg_source_info(self, acc, out):
        """
        :param acc: a dictionary {trt_model_id: sources}
        :param out: a SourceInfo instance
        """
        self.outs.append(
            (out.trt_model_id, out.source_id, out.source_class,
             len(out.sources), out.filter_time, out.split_time))
        return acc + {out.trt_model_id: out.sources}

    def process(self, csm):
        """
        :param csm: a CompositeSourceModel instance
        :param monitor: a monitor object
        :returns: the times spent in sequential and parallel processing
        """
        sources = csm.get_sources()
        fast_sources = [(src, self) for src in sources
                        if src.__class__.__name__ in
                        ('PointSource', 'AreaSource')]
        slow_sources = [(src, self) for src in sources
                        if src.__class__.__name__ not in
                        ('PointSource', 'AreaSource')]
        self.outs = []
        seqtime, partime = 0, 0
        sources_by_trt = AccumDict()

        # start multicore processing
        if slow_sources:
            t0 = time.time()
            logging.warn('Parallel processing of %d sources...',
                         len(slow_sources))
            ss = parallel.TaskManager.starmap(filter_and_split, slow_sources)

        # single core processing
        if fast_sources:
            logging.warn('Sequential processing of %d sources...',
                         len(fast_sources))
            t1 = time.time()
            sources_by_trt += reduce(
                self.agg_source_info,
                itertools.starmap(filter_and_split, fast_sources), AccumDict())
            seqtime = time.time() - t1

        # finish multicore processing
        sources_by_trt += (ss.reduce(self.agg_source_info)
                           if slow_sources else {})
        if slow_sources:
            partime = time.time() - t0
        # store csm.source_info
        source_info_dt = numpy.dtype(
            [('trt_model_id', int),
             ('source_id', (str, 20)),
             ('source_class', (str, 20)),
             ('split_num', int),
             ('filter_time', float),
             ('split_time', float)])
        self.outs.sort(key=lambda o: o[4] + o[5], reverse=True)
        csm.source_info = numpy.array(self.outs, source_info_dt)
        del self.outs[:]

        # update trt_model.sources
        for source_model in csm:
            for trt_model in source_model.trt_models:
                trt_model.sources = sorted(
                    sources_by_trt.get(trt_model.id, []),
                    key=operator.attrgetter('source_id'))
                if not trt_model.sources:
                    logging.warn(
                        'Could not find sources close to the sites in %s '
                        'sm_lt_path=%s, maximum_distance=%s km, TRT=%s',
                        source_model.name, source_model.path,
                        self.maxdist, trt_model.trt)

        return seqtime, partime
