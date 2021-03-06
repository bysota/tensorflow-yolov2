def iou(self, box1, box2):
    '''Compute ious between box1 and box2

    python function, box2 is the truth box by default

    Args:
        box1, box2: 1 x 4 ndarray, with format (xc, yc, w, h)
    Returns:
        overlaps: float32,  overlap between boxes and query_box 
    '''

    # Tranform (xc, yc, w, h) -> (x1, y1, x2, y2)
    box1 = np.array(([box1[0] - box1[2] / 2, \
                      box1[1] - box1[3] / 2, \
                      box1[0] + box1[2] / 2, \
                      box1[1] + box1[3] / 2]), 
                      dtype = np.float32)
    
    box2 = np.array(([box2[0] - box2[2] / 2, \
                      box2[1] - box2[3] / 2, \
                      box2[0] + box2[2] / 2, \
                      box2[1] + box2[3] / 2]),
                      dtype=np.float32)


    if box2[2] == 0 or box2[3] == 0:
        return 1.0
    
    else:
        # Calculate the left-up points and right-down points 
        # of overlap area
        lu = box1[0:2] * (box1[0:2] >= box2[0:2]) + \
                box2[0:2] * (box1[0:2] < box2[0:2])

        rd = box1[2:4] * (box1[2:4] <= box2[2:4]) + \
                box2[2:4] * (box1[2:4] > box2[2:4])

        # itersection = (iter_r - iter_l) * (iter_d - iter_u)
        intersection = rd - lu

        inter_square = intersection[0] * intersection[1]

        # Elimated those itersection with w or h < 0
        mask = np.array(intersection[0] > 0, np.float32) * \
               np.array(intersection[1] > 0, np.float32)

        inter_square = mask * inter_square
        
        # Calculate the boxes square and query_box square
        square1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        square2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        return inter_square / (square1 + square2 - inter_square + 1e-6)

def logistic(self, x):
    return 1./(1 + np.exp(-x))

def restore_box(self, box, h, w, map_height, map_width, prior_h, prior_w):
    '''Restore box (cx, cy, w, h) from predict info (tx, ty, tw, th)

    Args:
        box: (tx, ty, tw, th)
        h: the index in y-axis of feature map
        w: the index in x-axis of feature map
        map_height, map_width: the size of feature map
        prior_h, prior_w: the prior size of anchor
    Returns:
        box: (xc, yc, w, h), normalized
    '''
    box_x = (w + self.logistic(box[0])) / map_width
    box_y = (h + self.logistic(box[1])) / map_height
    box_w = np.exp(box[2]) * prior_w / map_width
    box_h = np.exp(box[3]) * prior_h / map_height
    return np.array([box_x, box_y, box_w, box_h])

def compute_coord_delta(self, box1, box2, h, w, map_height, map_width,
        prior_h, prior_w, scale):
    '''Compute the coords loss between box1 and box2

    Args:
        box1, box2: (xc, yc, w, h), box2 is gt_box
        h: the index in y-axis of feature map
        w: the index in x-axis of feature map
        map_height, map_width: the size of feature map
        prior_h, prior_w: the prior size of anchor
        scale: the coeffience for the square loss

    Returns:
        delta: (tx_delta, ty_delta, tw_delta, th_delta)
    '''
    
    # Transform (xc, yc, w, h) -> (log_tx, log_ty, tw, th)
    
    log_tx1 = box1[0] * map_width - w
    log_ty1 = box1[1] * map_height - h
    tw1 = np.log(box1[2] * map_width * 1.0 / prior_w)
    th1 = np.log(box1[3] * map_height * 1.0 / prior_h)

    log_tx2 = box2[0] * map_width - w
    log_ty2 = box2[1] * map_height - h
    tw2 = np.log(box2[2] * map_width  * 1.0 / prior_w)
    th2 = np.log(box2[3] * map_height * 1.0 / prior_h)

    delta = np.zeros(4, dtype=np.float32)
    delta[0] = scale * (log_tx2 - log_tx1)
    delta[1] = scale * (log_ty2 - log_ty1)
    delta[2] = scale * (tw2 - tw1)
    delta[3] = scale * (th2 - th1)

    return delta
    

def cal_loss_py(self, predicts, labels, obj_num, seen):
    '''Calculate loss between predicts and labels

    python function, callable for tensorflow using tf.py_func

    Args:
        predicts: Commonly batch x map_height x map_width x boxes_info
                  boxes_info: info for several (commonly 5) boxes,
                  including coords(4), object(1), class_prob(class_num)
        labels: ground-truth bounding box, batch x 30 x 
                (cls(1), coords(4))
        obj_num: batch x 1, indicate the number of objs in an image
        seen: The number of pictures that have been fed into the network
    Returns:
        loss:  batch x 1, for each image
    Warnings:
        Note that the real box coords in predicts can only be grained after
        applying function self.restore_box()
    '''

    batch_size = cfg.TRAIN.BATCH
    map_height = predicts.shape[1]
    map_width = predicts.shape[2]

    box_num = cfg.TRAIN.BOX_NUM
    
    # The len of infomation for each box
    box_info_len = 4 + 1 + len(cfg.TRAIN.CLASSES)
    
    # Four evaluation criterions
    recall = 0
    avg_iou = 0
    avg_obj = 0
    avg_cat = 0
    avg_anyobj = 0

    # Total objects in labels
    obj_count = 0

    delta = np.zeros((batch_size, map_height, map_width, box_num * box_info_len),
            dtype = np.float32)

    for b in range(batch_size):
        label_this_batch = labels[b, 0:obj_num[b], :]
        predict_this_batch = predicts[b, :, :, :]
        for h in range(map_height):
            for w in range(map_width):
                for k in range(box_num):
                    box_info = predict_this_batch[h, w, 
                            k * box_info_len: (k+1) * box_info_len]

                    prior_w = cfg.TRAIN.ANCHORS[2*k]
                    prior_h = cfg.TRAIN.ANCHORS[2*k+1]
                    box = self.restore_box(box_info[0:4], h, w, map_height,
                            map_width, prior_h, prior_w)
                    
                    gt_boxes = np.array(label_this_batch[:, 1:5])
                    box_iou = 0
                    for gb in gt_boxes:
                        iou = self.iou(box, gb)
                        if iou > box_iou:
                            box_iou = iou 
                   
                    if box_iou > cfg.TRAIN.THRESH:
                        # If the box iou exceed overlaps,
                        # then the loss is zero.
                        # Loss of some boxes will be recalculated in the
                        # following.
                        delta[b, h, w, k*box_info_len+4] = 0
                    else:
                        delta[b, h, w, k*box_info_len+4] = \
                            cfg.TRAIN.NOOBJECT_SCALE * (0 - self.logistic(box_info[4]))

                    avg_anyobj += self.logistic(box_info[4])


                    if seen < 0:
                        # In the early feeding for 12800 pictures,
                        # the coord loss for each box should be calculated.
                        # Here, the loss is the deviated from the prior
                        # anchor.
                        truth_box_x = (w + 0.5) / map_width
                        truth_box_y = (h + 0.5) / map_height
                        truth_box_w = prior_w * 1.0/ map_width
                        truth_box_h = prior_h * 1.0/ map_height
                        truth_box = np.array([truth_box_x, truth_box_y,
                                              truth_box_w, truth_box_h])

                        delta[b, h, w, k*box_info_len : k*box_info_len+4] = \
                                self.compute_coord_delta(box, truth_box, \
                                h, w, map_height, map_width, prior_h, prior_w, 0.01)

        obj_count += obj_num[b]
        for m in range(obj_num[b]):
            """
            For each gt_box, we find one responsible pred box,
            and compute coord loss, obj loss, class loss for that pred box
            """
            current_label = label_this_batch[m,: ]
            truth_box = current_label[1:5]
            
            if truth_box[2] == 0 or truth_box[3] == 0:
                continue

            else:
                # Find the pixel index w.r.t feature map
                w = min(int(truth_box[0] * map_width), map_width-1)
                h = min(int(truth_box[1] * map_height), map_height-1)
                
                best_iou = 0
                best_idx = 0

                prior_w = cfg.TRAIN.ANCHORS[2*k]
                prior_h = cfg.TRAIN.ANCHORS[2*k+1]
               
                # Find the best matching pred box for gt box 
                for k in range(box_num):
                    box_info = predict_this_batch[h, w, k * box_info_len: (k+1)
                            * box_info_len]

                    box = self.restore_box(box_info[0:4], h, w, map_height, 
                                map_width, prior_h, prior_w)

                    # We make the centroids of truth_box and box the same
                    truth_shift = copy.deepcopy(truth_box)
                    truth_shift[0] = 0.0
                    truth_shift[1] = 0.0

                    box[0] = 0.0
                    box[1] = 0.0

                    box_iou = self.iou(box, truth_shift)

                    if box_iou > best_iou:
                        best_iou = box_iou
                        best_idx = k

                best_box_info = predict_this_batch[h, w, best_idx *
                        box_info_len: (best_idx+1) * box_info_len]

                best_box = self.restore_box(best_box_info[0:4], h, w,
                        map_height, map_width, prior_h, prior_w)

                # Recalculate iou
                best_iou = self.iou(best_box, truth_box)

                if best_iou > 0.5:
                    recall += 1

                avg_iou += best_iou

                avg_obj += self.logistic(best_box_info[4])

                # Coords loss
                delta[b, h, w, best_idx * box_info_len: best_idx * box_info_len +
                        4] = self.compute_coord_delta(best_box, truth_box, \
                                h, w, map_height, map_width, prior_h, prior_w,\
                                cfg.TRAIN.COORD_SCALE * (2 - truth_box[2]*truth_box[3]))

                # Object loss
                delta[b, h, w, best_idx * box_info_len + 4] = \
                        cfg.TRAIN.OBJECT_SCALE * (best_iou - self.logistic(best_box_info[4]))

                # class prob loss
                cls = int(truth_box[0])   # class index for current gt box
                temp = np.zeros(len(cfg.TRAIN.CLASSES), dtype = np.float32)
                temp[cls] = 1.0

                delta[b, h, w, best_idx * box_info_len + 5: (best_idx + 1) *
                        box_info_len] = cfg.TRAIN.CLASS_SCALE * (temp -
                                best_box_info[5:])

                avg_cat += best_box_info[5 + cls]

    print("Region Avg IOU: %f, Class: %f, Obj: %f, No Obj: %f, Avg Recall :%f, count %d"
            %(avg_iou/obj_count, avg_cat/obj_count, avg_obj/obj_count, 
              avg_anyobj/(map_width*map_height*self.num_outputs*batch_size),
              recall/obj_count, obj_count))

    delta = np.square(delta)

    # Record coord loss, object loss and class loss
    coord_loss = 0
    object_loss = 0
    class_loss = 0
    for b in range(batch_size):
        for h in range(map_height):
            for w in range(map_width):
                for k in range(box_num):
                    coord_loss += sum(delta[b, h, w, k*box_info_len :
                            k*box_info_len + 4])
                    object_loss += delta[b, h, w, k*box_info_len + 4]
                    class_loss += sum(delta[b, h, w, k*box_info_len+5:])

    tf.summary.scalar('coord_loss', tf.constant(coord_loss, tf.float32))
    tf.summary.scalar('object_loss', tf.constant(object_loss, tf.float32))
    tf.summary.scalar('class_loss', tf.constant(class_loss, tf.float32))

    delta = delta.reshape((batch_size, -1))

    delta = np.sum(delta, axis = 1)

    return delta

