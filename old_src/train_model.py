import pandas as pd
import numpy as np
from sklearn import preprocessing
from scipy import stats
from sklearn.preprocessing import StandardScaler
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

# %matplotlib inline


import mkl
mkl.set_num_threads(1)

import multiprocessing as mp
from sklearn.linear_model import Lasso
from sklearn.model_selection import GridSearchCV

def Train_all_tissue_aging_model(md_hot_train, df_prot_train,
                                 tissue_plist_dict, seed_list, 
                                 performance_CUTOFF, train_cohort,
                                 norm, agerange, NPOOL=15):
    seed_list = seed_list['BS_Seed']
    NUM_BOOTSTRAP=len(seed_list)
    print(seed_list)
    # final lists for output
    all_coef_dfs = []   
    
    # bootstrap clocks for each tissue
    for tissue,plist in tissue_plist_dict.items():
        if len(plist)>0:            
            print(tissue) 
            
            # Subset to tissue proteins, setup dfX/dfY
            df_prot_train_tissue = df_prot_train[plist]
            
            # zscore
            scaler = StandardScaler()
            scaler.fit(df_prot_train_tissue)
            tmp = scaler.transform(df_prot_train_tissue)
            df_prot_train_tissue = pd.DataFrame(tmp, index=df_prot_train_tissue.index, columns=df_prot_train_tissue.columns)
            
            # save the scaler
            path = 'train/data/ml_models/'+train_cohort+'/'+agerange+'/'+norm+'/'+tissue
            fn = '/'+train_cohort+'_'+agerange+'_based_'+tissue+'_protein_zscore_scaler.pkl'
            os.makedirs(path)
            pickle.dump(scaler, open(path+fn, 'wb'), protocol=pickle.HIGHEST_PROTOCOL)
    
            # add sex 
            if "Sex_F" in list(md_hot_train.columns):
                df_X_train = pd.concat([md_hot_train[["Sex_F"]], df_prot_train_tissue], axis=1)
            else:
                df_X_train = df_prot_train_tissue.copy()
            df_Y_train = md_hot_train[["Age"]].copy()
    
            # Bootstrap training
            pool = mp.Pool(NPOOL)
            input_list = [([df_X_train, df_Y_train, train_cohort,
                            tissue, performance_CUTOFF, norm, agerange] + [seed_list[i]]) for i in range(NUM_BOOTSTRAP)]        
            coef_list = pool.starmap(Bootstrap_train, input_list)
            pool.close()
            pool.join()
            
            df_tissue_coef = pd.DataFrame(coef_list, columns=["tissue", "BS_Seed", "alpha", "y_intercept"]+list(df_X_train.columns))
            all_coef_dfs.append(df_tissue_coef)
    dfcoef=pd.concat(all_coef_dfs, join="outer")
    return dfcoef
  
    
def Bootstrap_train(df_X_train, df_Y_train, train_cohort,
              tissue, performance_CUTOFF, norm, agerange, seed):
    
    #setup
    X_train_sample = df_X_train.sample(frac=1, replace=True, random_state=seed).to_numpy()
    Y_train_sample = df_Y_train.sample(frac=1, replace=True, random_state=seed).to_numpy()    
    
    # LASSO
    lasso = Lasso(random_state=0, tol=0.01, max_iter=5000)
    alphas = np.logspace(-3, 1, 100)
    tuned_parameters = [{'alpha': alphas}]
    n_folds=5
    clf = GridSearchCV(lasso, tuned_parameters, cv=n_folds, scoring="neg_mean_squared_error", refit=False)
    clf.fit(X_train_sample, Y_train_sample)
    gsdf = pd.DataFrame(clf.cv_results_)    
    best_alpha=Plot_and_pick_alpha(gsdf, performance_CUTOFF, plot=False)   #pick best alpha
     
    # Retrain 
    lasso = Lasso(alpha=best_alpha, random_state=0, tol=0.01, max_iter=5000)
    lasso.fit(X_train_sample, Y_train_sample)

    # SAVE MODEL
    savefp="train/data/ml_models/"+train_cohort+"/"+agerange+"/"+norm+"/"+tissue+"/"+train_cohort+"_"+agerange+"_"+norm+"_lasso_"+tissue+"_seed"+str(seed)+"_aging_model.pkl"
    pickle.dump(lasso, open(savefp, 'wb'))
    
    # SAVE coefficients            
    coef_list = [tissue, seed, best_alpha, lasso.intercept_[0]] + list(lasso.coef_)

    return coef_list
    


def Plot_and_pick_alpha(gsdf, performance_CUTOFF, plot=True):
    
    #pick alpha at 90-95% top performance, negative derivative (higher alpha)
    gsdf["mean_test_score_norm"] = NormalizeData(gsdf["mean_test_score"])
    gsdf["mean_test_score_norm_minus95"] = gsdf["mean_test_score_norm"]-performance_CUTOFF
    gsdf["mean_test_score_norm_minus95_abs"] = np.abs(gsdf["mean_test_score_norm_minus95"])

        #derivative of performance by alpha
    x=gsdf.param_alpha.to_numpy()
    y=gsdf.mean_test_score_norm.to_numpy()
    dx=0.1
    gsdf["derivative"] = np.gradient(y, dx)
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
    


agerange="HC"
performance_CUTOFF=0.95
norm="Zprot_perf"+str(int(performance_CUTOFF*100))
train_cohort="KADRC"

md_hot_train = pd.read_csv("tests/md_hot.csv").set_index("ID")
df_prot_train = pd.read_csv("tests/df_prot.csv").set_index("ID")
tissue_plist_dict = json.load(open("train/data/tissue_pproteinlist_5k_dict_gtex_tissue_enriched_fc4_stable_assay_proteins_seqid.json"))
bs_seed_list = json.load(open("train/data/Bootstrap_and_permutation_500_seed_dict.json"))

#95% performance
start_time = time.time()
dfcoef = Train_all_tissue_aging_model(md_hot_train, #meta data dataframe with age and sex (binary) as columns
                                       df_prot_train, #protein expression dataframe with SeqIds as columns
                                       tissue_plist_dict, #tissue:protein list dictionary
                                       bs_seed_list, #bootstrap seeds
                                       performance_CUTOFF=performance_CUTOFF, #heuristic for model simplification
                                       NPOOL=15, #parallelize
                                       
                                       train_cohort=train_cohort, #these three variables for file naming
                                       norm=norm, 
                                       agerange=agerange, 
                                       )
print((time.time() - start_time)/60)
