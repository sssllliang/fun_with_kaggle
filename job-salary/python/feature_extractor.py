## build feature_extractor model
from sklearn.base import BaseEstimator
from sklearn.feature_extraction import text
from sklearn import feature_extraction
from sklearn import cluster
from sklearn import linear_model
from joblib import Parallel, delayed
from scipy import sparse
import re, csv, sys
import numpy as np
import pandas as pd


class BOWFeatureExtractor(BaseEstimator):
    def __init__(self, field, max_features = 1000, 
                min_df = 0.05, max_df = 0.95, 
                ngram_range = (1, 1),
                selected_features = None):
        ## max_features selects features based on their term frequences
        ## it makes a HUGE difference from randomly selecting the features
        self.counter = text.CountVectorizer(stop_words = 'english', 
                        ngram_range = ngram_range, binary = True, 
                        max_features = max_features,
                        max_df = max_df, min_df = min_df,
                        lowercase = True)
        self.field = field
        self.selected_features = selected_features
    def fit(self, X, y=None):
        self.counter.fit(X[self.field])
        return self
    def transform(self, X):
        result = self.counter.transform(X[self.field])
        if self.selected_features:
            result = result.tocsc()[:, self.selected_features]
        return result
    def fit_transform(self, X, y=None):
        return self.fit(X, y).transform(X)

class DescriptionSimplifier(BaseEstimator):
    def __init__(self):
        self.pattern = re.compile(r'\b[A-Z]\w+\b')
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        X['FullDescription'] = map(
            lambda desc: ' '.join(self.pattern.findall(desc))
            , X['FullDescription'])
        return X
    def fit_transform(self, X, y=None):
        return self.fit(X, y).transform(X)

        
class LocationFeatureExtractor(BaseEstimator):
    def __init__(self, max_features = 100):
        self.field = 'ProcessedLocation'
        self.counter = BOWFeatureExtractor(self.field, max_features = max_features, max_df = 1, min_df = 1)
        self.LOCATION_TREE_FILE = '../data/Location_Tree.csv'
        ## BUILD dictionary based on location_tree - faster for search
        location_tree = [row[0].lower().split('~')[::-1] for row in csv.reader(open(self.LOCATION_TREE_FILE))]
        self.location_dict = {}
        for locs in location_tree:
            for i in range(len(locs)):
                if locs[i] not in self.location_dict:
                    self.location_dict[locs[i]] = locs[i:]
    def fit(self, X, y=None):
        X = self._preprocess(X)
        self.counter.fit(X, y)
        return self
    def transform(self, X):
        X = self._preprocess(X)
        return self.counter.transform(X)
    def fit_transform(self, X, y=None):
        return self.fit(X, y).transform(X)
    def _preprocess(self, X):
        ## preprocessing
        (raw_locations, locations) = X['LocationRaw'].tolist(), X['LocationNormalized'].tolist()
        ## BUILD first term of raw_location -- more informative than normalized location
        pattern = re.compile(r'\b[\w\s]+')
        locations_initial = map(lambda s: pattern.findall(s), raw_locations)
        locations_initial = map(lambda (i,s): s[0] if (s and s[0] in self.location_dict) else locations[i],
                                        enumerate(locations_initial))
        ## strategy: pick the first word from LocationRaw, 
        ## if found in the tree, use it, otherwise use LocationNormlalized
        ## the above data structure could be slow when searching
        processed_locations = np.array([' '.join(self.location_dict[initial]) 
                                                if initial in self.location_dict 
                                                else 'UK' 
                                            for initial in locations_initial]) ## CAPTITAL 'UK' for unfound
        X[self.field] = processed_locations
        return X

class CompanyOneHotFeatureExtractor(BaseEstimator):
    def __init__(self):
        self.field = 'Company'
        self.rm_pattern = re.compile('ltd|limited', re.IGNORECASE)
        self.field_values = []
        self.na_class = 'miss'
        self.na_string = 'nan'
        self.dicter = feature_extraction.DictVectorizer()
    def fit(self, X, y=None):
        sub_X = np.array(X[self.field].tolist())
        sub_X[sub_X==self.na_string] = self.na_class
        sub_X = map(
            lambda com: self.rm_pattern.sub('', com.lower()).strip(),
            sub_X
        )
        self.field_values = set(np.unique(sub_X))
        sub_X = [{self.field:v} for v in sub_X]
        self.dicter.fit(sub_X)
        return self
    def transform(self, X):
        #print "!!!!!!!!!!!!DEBUG:", type(X), X.columns
        sub_X = np.array(X[self.field].tolist())
        sub_X[sub_X==self.na_string] = self.na_class
        sub_X = map(
            lambda com: self.rm_pattern.sub('', com.lower()).strip(),
            sub_X
        )
        sub_X = map(
            lambda com: com if (com in self.field_values) else self.na_class,
            sub_X
        )
        sub_X = [{self.field:v} for v in sub_X]
        
        sub_X = self.dicter.transform(sub_X)
        #print sub_X.shape
        return sub_X
    def fit_transform(self, X, y=None):
        return self.fit(X, y).transform(X)

class OneHotNAFeatureExtractor(BaseEstimator):
    def __init__(self, field, na_string = "nan", na_class = 'miss'):
        self.na_string = na_string
        self.na_class = na_class
        self.field = field
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        sub_X = np.array(X[self.field].tolist())
        sub_X[sub_X==self.na_string] = self.na_class
        sub_X = [{self.field:v} for v in sub_X]
        dicter = feature_extraction.DictVectorizer()
        sub_X = dicter.fit_transform(sub_X)
        return sub_X
    def fit_transform(self, X, y=None):
        return self.fit(X, y).transform(X)
        

def TitleClusterFeatureExtractor_trans(level, salary, titles, counter): 
    return (counter.transform(titles), salary)   
def TitleClusterFeatureExtractor_clus(CounterX, salary): 
    return (cluster.MiniBatchKMeans(n_clusters = 1).fit(CounterX), salary) 
def TitleClusterFeatureExtractor_dist(km, CounterX): 
    return km.transform(CounterX)   
class TitleClusterFeatureExtractor(BaseEstimator):
    def __init__(self, n_levels = 1000):
        self.n_levels = n_levels
        self.counter = text.CountVectorizer(stop_words = 'english', binary = True, charset_error='ignore',
                                lowercase = True, min_df=1, charset='utf-8', token_pattern=r'\b[a-z][a-z]+\b', 
                                #max_features = 500,
                        )
    def fit(self, X, y=None):
        """y could be transformed or not
        """
        self.counter.fit(X['Title'])
        min_y, max_y = y.min(), y.max()
        X['SalaryLevels'] = np.digitize(y.tolist(), 
                    bins = np.linspace(min_y, max_y, (max_y-min_y)/self.n_levels+1))
        X['TitleY'] = y
        salary_groups = X.groupby('SalaryLevels')
        title_groups = [(salary_level, 
                        groups['TitleY'].mean(), 
                        ' '.join(map(str, groups['Title'].tolist()))) 
                            for (salary_level, groups) in salary_groups]
        """
        CounterX_groups = Parallel(n_jobs=-1)(delayed(TitleClusterFeatureExtractor_trans)
                                                          (level, salary, titles, self.counter) 
                                        for (level, salary, titles) in title_groups)
        self.ClusterX_groups = Parallel(n_jobs=-1)(delayed(TitleClusterFeatureExtractor_clus)(CounterX, salary) 
                        for (CounterX, salary) in CounterX_groups)
        """
        CounterX_groups = [TitleClusterFeatureExtractor_trans(level, salary, titles, self.counter) 
                                                        for (level, salary, titles) in title_groups]
        self.ClusterX_groups = [TitleClusterFeatureExtractor_clus(CounterX, salary) 
                                                        for (CounterX, salary) in CounterX_groups]
        
        self.clusters = np.array(map(lambda (km, salary): km, self.ClusterX_groups))
        self.salaries = np.array(map(lambda (km, salary): salary, self.ClusterX_groups))
        
        return self
    def transform(self, X):
        CounterX = self.counter.transform(X['Title'])
        distances = Parallel(n_jobs=-1)(delayed(TitleClusterFeatureExtractor_dist)(km, CounterX) 
                        for km in self.clusters)
        #print distances_salary[0][0]
        #print distances_salary[0][0].shape
        dist_mat = np.hstack(distances)
        cluster_labels = np.argmin(dist_mat, axis = 1)
        return self.salaries[cluster_labels].reshape(-1, 1)
    def fit_transform(self, X, y=None):
        return self.fit(X, y).transform(X)

class ContractTimeImputator(BaseEstimator):
    def __init__(self):
        pass
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        missed_contract_time = X.index[np.where(pd.isnull(X['ContractTime']))[0]]
        to_be_permanent = [i for i in missed_contract_time if 'permanent' in X['FullDescription'][i].lower()]
        contract_pattern = re.compile(r'\bcontract\b')
        to_be_contract = [i for i in missed_contract_time if contract_pattern.findall(X['FullDescription'][i].lower())]
        #print '!!!!!!DEBUG:', to_be_imputate[:10]
        print 'DEBUG: ', len(to_be_permanent), 'ContractTime entries can be imputated as permanent'
        print 'DEBUG: ', len(to_be_contract), 'ContractTime entries can be imputated as contract'
        X.ix[to_be_permanent, 'ContractTime'] = 'permanent'
        X.ix[to_be_contract, 'ContractTime'] = 'contract'
        return X
    def fit_transform(self, X, y=None):
        return self.fit(X, y).transform(X)


class ContractTypeImputator(BaseEstimator):
    def __init__(self):
        pass
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        missed_contract_type = X.index[np.where(pd.isnull(X['ContractType']))[0]]
        to_be_full = [i for i in missed_contract_type if 'full time' in X['FullDescription'][i].lower()]
        to_be_part = [i for i in missed_contract_type if 'part time' in X['FullDescription'][i].lower()]
        #print '!!!!!!DEBUG:', to_be_imputate[:10]
        print 'DEBUG: ', len(to_be_full), 'ContractType entries can be imputated as full_time'
        print 'DEBUG: ', len(to_be_part), 'ContractType entries can be imputated as part_time'
        X.ix[to_be_full, 'ContractType'] = 'full_time'
        X.ix[to_be_part, 'ContractType'] = 'part_time'
        return X
    def fit_transform(self, X, y=None):
        return self.fit(X, y).transform(X)

class SGDFeatureSelector(BaseEstimator):
    def __init__(self, l1_ratio=0.15, coef_threshold = 0):
        self.regressor = linear_model.SGDRegressor(loss='huber', penalty='l1', 
                            alpha=0.0005, l1_ratio=l1_ratio, verbose=1)
        self.coef_threshold = coef_threshold
    def fit(self, X, y=None):
        self.regressor.fit(X, y)
        if self.coef_threshold is None:
            self.coef_threshold = (max(self.regressor.coef_) - min(self.regressor.coef_))/2.
        self.selected_features = np.where(abs(np.array(self.regressor.coef_)) > self.coef_threshold)[0]
        #self.selected_features = range(X.shape[1])
        #print '!!!!!!!!!!DEBUG:', self.regressor.coef_
        print 'DEBUG: SGD selects ', len(self.selected_features), ' out of ', X.shape[1]
        return self
    def transform(self, X):
        return X.tocsc()[:, self.selected_features]
    def fit_transform(self, X, y=None):
        return self.fit(X, y).transform(X)

def feature_fit(name, transformer, X, y = None):
    return (name, transformer.fit(X, y))
def feature_transform(transformer, X):
    return transformer.transform(X)
class SpaseFeatureUnion(BaseEstimator):
    def __init__(self, transformers):
        self.transformers = transformers
    def fit(self, X, y = None):
        self.transformers = Parallel(n_jobs = -1)(delayed(feature_fit)(name, transformer, X, y) 
                                                for (name, transformer) in self.transformers)
        return self
    def transform(self, X):    
        results = Parallel(n_jobs = -1)(delayed(feature_transform)(transformer, X) 
                                        for (name, transformer) in self.transformers)
        merged = sparse.hstack(results)
        return merged
    def fit_transform(self, X, y = None):
        return self.fit(X, y).transform(X)
        