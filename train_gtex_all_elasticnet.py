import pandas as pd
import numpy as np
import warnings
np.warnings = warnings
from sklearn import preprocessing
from scipy import stats
from sklearn.preprocessing import StandardScaler, MinMaxScaler, RobustScaler, PowerTransformer
from sklearn.model_selection import train_test_split
import matplotlib.pyplot as plt
from matplotlib.pyplot import figure
import seaborn as sns
from scipy.stats import zscore
from sklearn import metrics
import json
import pickle
import time
import random 
import os
from adjustText import adjust_text
import sys
from sdv.single_table import TVAESynthesizer
from sdv.metadata import Metadata
import torch

# Check if GPU is available
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")

# %matplotlib inline
import mkl
mkl.set_num_threads(1)

import multiprocessing as mp
from sklearn.linear_model import Lasso, LogisticRegression, Ridge, ElasticNet, HuberRegressor
from sklearn.model_selection import GridSearchCV


def Train_tissue_aging_model_elasticnet (tissue, md_hot_train, df_prot_train,
                                 seed_list, 
                                 performance_CUTOFF, train_cohort,
                                 norm, agerange, n_bs, split_id, NPOOL=15):
    NUM_BOOTSTRAP = int(n_bs)
    seed_list = seed_list['BS_Seed']
    seed_list = seed_list[:NUM_BOOTSTRAP]
    print(seed_list)
    # final lists for output
    print ("STARTING TRAINING FOR " + tissue)
    df_prot_train_tissue = df_prot_train (tissue)
    df_prot_train_tissue.index.names = ['SUBJID']
    md_hot_train_tissue = md_hot_train.merge(right = df_prot_train_tissue.index.to_series(), how='inner', left_index=True, right_index=True)

    # zscore
    # scaler = MinMaxScaler(feature_range = (0,1))
    # scaler = RobustScaler()
    # scaler = StandardScaler()
    scaler = PowerTransformer(method='yeo-johnson')
    scaler.fit(df_prot_train_tissue)
    tmp = scaler.transform(df_prot_train_tissue)
    df_prot_train_tissue = pd.DataFrame(tmp, index=df_prot_train_tissue.index, columns=df_prot_train_tissue.columns)
    print (df_prot_train_tissue)

    # save the scaler
    path = 'gtex/train_splits/train_bs' + n_bs + '_' + split_id + '/data/ml_models/'+train_cohort+'/'+agerange+'/'+norm+'/'+tissue
    fn = '/'+train_cohort+'_'+agerange+'_based_'+tissue+'_gene_zscore_scaler.pkl'
    os.makedirs (path, exist_ok=True)
    pickle.dump (scaler, open(path+fn, 'wb'), protocol=pickle.HIGHEST_PROTOCOL)
    print("z-scaler is ready...")

    # add sex 
    if "SEX" in list(md_hot_train_tissue.columns):
        # print(md_hot_train[["SEX"]])
        df_X_train = pd.concat([md_hot_train_tissue[["SEX"]], df_prot_train_tissue], axis=1)
    else:
        df_X_train = df_prot_train_tissue.copy()
    df_Y_train = md_hot_train_tissue[["AGE"]].copy()
    
    print (df_X_train)
    # comb_data = pd.concat ([df_X_train, df_Y_train], axis=1)
    # print (comb_data)
    # mdata = Metadata.detect_from_dataframe(
    #         data=comb_data,
    #         table_name='combined'
    # )
    # mdata.update_column(
    #     column_name='SEX',
    #     sdtype='categorical',
    #     table_name='combined'
    # )
    # mdata.update_column(
    #     column_name='AGE',
    #     sdtype='categorical',
    #     table_name='combined'
    # )
    # synth = TVAESynthesizer (
    #     metadata= mdata,
    #     enforce_min_max_values=True,
    #     epochs=50,
    #     verbose=True,
    # )
    # synth.fit (comb_data)
    # synthetic_data = synth.sample(num_rows=3000)
    # y_synth = synthetic_data[['AGE']]
    # X_synth = synthetic_data.drop(columns=['AGE'])
    # print (X_synth)
    # print (y_synth)

    # Bootstrap training
    print ("starting bootstrap training...")
    pool = mp.Pool(NPOOL)
    input_list = [([df_X_train, df_Y_train, train_cohort,
                    tissue, performance_CUTOFF, norm, agerange, n_bs, split_id] + [seed_list[i]]) for i in range(NUM_BOOTSTRAP)]        
    # input_list = [([X_synth, y_synth, train_cohort,
    #                 tissue, performance_CUTOFF, norm, agerange, n_bs, split_id] + [seed_list[i]]) for i in range(NUM_BOOTSTRAP)]        
    
    coef_list = pool.starmap(Bootstrap_train, input_list)
    pool.close()
    pool.join()
    coef_list = pd.concat(coef_list, axis=1).mean(axis=1).abs().sort_values(ascending=False)
    return coef_list          

def Train_all_tissue_aging_model_elasticnet(md_hot_train, df_prot_train,
                                 seed_list, 
                                 performance_CUTOFF, train_cohort,
                                 norm, agerange, n_bs, split_id, NPOOL=15):
    # NUM_BOOTSTRAP = int(n_bs)
    # seed_list = seed_list['BS_Seed']
    # seed_list = seed_list[:NUM_BOOTSTRAP]
    # print(seed_list)
    # final lists for output
    all_coef_dfs = []   
    
    with open('gtex/organ_list.dat', 'r') as file:
        tissues = [line.strip() for line in file]

    # Subset to tissue proteins, setup dfX/dfY
    for tissue in tissues:
        dfcoef = Train_tissue_aging_model_elasticnet (
            tissue, md_hot_train, df_prot_train,
            seed_list, 
            performance_CUTOFF, train_cohort,
            norm, agerange, n_bs, split_id, NPOOL=15
        )
        print (dfcoef)
    return dfcoef
  
    
def Bootstrap_train(df_X_train, df_Y_train, train_cohort,
              tissue, performance_CUTOFF, norm, agerange, n_bs, split_id, seed):
    
    #setup
    X_train_sample = df_X_train.sample(frac=1, replace=True, random_state=seed).to_numpy()
    Y_train_sample = df_Y_train.sample(frac=1, replace=True, random_state=seed).to_numpy()    
    print("did bootstrap setup... (seed = ", seed, ")")
    
    # LASSO
    print ("starting elasticnet?... (seed = ", seed, ")")
    # lasso = Lasso(random_state=0, alpha=0.05, tol=0.01, max_iter=5000)
    lasso = ElasticNet(random_state=0, tol=0.01, max_iter=50000, l1_ratio=0.5)
    alphas = np.logspace(-3, 1, 150)
    tuned_parameters = [{'alpha': alphas}]
    n_folds=4
    print("initialised elasticnet params setup... (seed = ", seed, ")")
    clf = GridSearchCV(lasso, tuned_parameters, cv=n_folds, scoring="neg_mean_absolute_error", refit=False)

    print("gridSearch done... (seed = ", seed, ")")
    clf.fit(X_train_sample, Y_train_sample)
    print("gridSearch fitting done... (seed = ", seed, ")")
    gsdf = pd.DataFrame(clf.cv_results_)    
    print("Plot nad Pick STARTING :(... (seed = ", seed, ")")
    best_alpha=Plot_and_pick_alpha(gsdf, performance_CUTOFF, plot=False)   #pick best alpha
    print("Plot nad Pick done... (seed = ", seed, ")")
    # Retrain 
    lasso = ElasticNet(alpha=best_alpha, random_state=0, tol=0.01, max_iter=50000)
    lasso.fit(X_train_sample, Y_train_sample)
    print ("elasticnet retrained.. (seed = ", seed, ")")
    # SAVE MODEL
    savefp="gtex/train_splits/train_bs" + n_bs + "_" + split_id + "/data/ml_models/"+train_cohort+"/"+agerange+"/"+norm+"/"+tissue+"/"+train_cohort+"_"+agerange+"_"+norm+"_elasticnet_"+tissue+"_seed"+str(seed)+"_aging_model.pkl"
    pickle.dump(lasso, open(savefp, 'wb'))
    # SAVE coefficients            
    coef_list = lasso.coef_.flatten() # You can adjust this if more details are needed
    coefficients_df = pd.Series(coef_list, index=df_X_train.columns)
    print (coefficients_df)
    return coefficients_df
    


def Plot_and_pick_alpha(gsdf, performance_CUTOFF, plot=True):
    
    #pick alpha at 90-95% top performance, negative derivative (higher alpha)
    gsdf["mean_test_score_norm"] = NormalizeData(gsdf["mean_test_score"])
    print ("P&P normalised...")
    gsdf["mean_test_score_norm_minus95"] = gsdf["mean_test_score_norm"]-performance_CUTOFF
    print ("P&P normalised and cut off...")
    gsdf["mean_test_score_norm_minus95_abs"] = np.abs(gsdf["mean_test_score_norm_minus95"])
    print ("P&P finding derivative...")
        #derivative of performance by alpha
    x=gsdf.param_alpha.to_numpy()
    y=gsdf.mean_test_score_norm.to_numpy()
    dx=0.1
    gsdf["derivative"] = np.gradient(y, dx)
    print ("P&P FOUND derivative...")
    tmp=gsdf.loc[gsdf.derivative<0]
    if len(tmp)!=0:
        best_alpha = list(tmp.loc[tmp.mean_test_score_norm_minus95_abs == np.min(tmp.mean_test_score_norm_minus95_abs)].param_alpha)[0]
    else:
        print('no alpha with derivative <0')
        tmp2=gsdf
        best_alpha = list(tmp2.loc[tmp2.mean_test_score_norm_minus95_abs == np.min(tmp2.mean_test_score_norm_minus95_abs)].param_alpha)[0]
        
    # PLOT
    if plot:
        fig,axs=plt.subplots(1,2,figsize=(7,3))
        sns.scatterplot(data=gsdf, x="param_alpha", y="mean_test_score_norm", ax=axs[0])
        sns.scatterplot(data=gsdf.loc[gsdf.param_alpha==best_alpha], x="param_alpha", y="mean_test_score_norm", ax=axs[0])
        sns.scatterplot(data=gsdf, x="param_alpha", y="mean_test_score_norm", ax=axs[1])
        sns.scatterplot(data=gsdf.loc[gsdf.param_alpha==best_alpha], x="param_alpha", y="mean_test_score_norm", ax=axs[1])
        axs[0].set_xlim(-0.02,best_alpha+0.1)
        axs[0].set_ylim(0.8,1.05)
        axs[0].axvline(0.008)
        axs[0].axhline(performance_CUTOFF)
        plt.tight_layout()
        plt.show()
    return best_alpha
    
    
def NormalizeData(data):
    return (data - np.min(data)) / (np.max(data) - np.min(data))
    

if __name__ == "__main__":
    agerange="HC"
    performance_CUTOFF=0.95
    norm="Zprot_perf"+str(int(performance_CUTOFF*100))
    train_cohort="gtexV8"

    gene_sort_crit = sys.argv[1]
    n_bs = sys.argv[2]
    split_id = sys.argv[3]
    if gene_sort_crit != '20p' and gene_sort_crit != '1000' and gene_sort_crit != 'deg' and gene_sort_crit != 'AA':
        print ("Invalid gene sort criteria")
        exit (1)
    if int(n_bs) > 500:
        print ("n_bs > 500 not possible")
        exit (1)

    def df_prot_train (tissue):
        return pd.read_csv(filepath_or_buffer="../../../gtex/proc/proc_data/reduced/corr" + gene_sort_crit + "/"+tissue+".TRAIN." + split_id + ".tsv", sep='\s+').set_index("Name")
        # return pd.read_csv(filepath_or_buffer="../../../gtex/gtexv8_coronary_artery_TRAIN.tsv", sep='\s+').set_index("Name")

    from md_age_ordering import return_md_hot
    md_hot_train = return_md_hot()

    bs_seed_list = json.load(open("gtex/Bootstrap_and_permutation_500_seed_dict_500.json"))

    #95% performance
    start_time = time.time()
    dfcoef = Train_all_tissue_aging_model_elasticnet(md_hot_train, #meta data dataframe with age and sex (binary) as columns
                                        df_prot_train, #protein expression dataframe returning method (by tissue)
                                        bs_seed_list, #bootstrap seeds
                                        performance_CUTOFF=performance_CUTOFF, #heuristic for model simplification
                                        NPOOL=1, #parallelize
                                        
                                        train_cohort=train_cohort, #these three variables for file naming
                                        norm=norm, 
                                        agerange=agerange, 
                                        n_bs=n_bs,
                                        split_id=split_id
                                        )
    print((time.time() - start_time)/60)
