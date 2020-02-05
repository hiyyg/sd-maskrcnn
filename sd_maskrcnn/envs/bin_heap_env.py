"""
Copyright ©2019. The Regents of the University of California (Regents). All Rights Reserved.
Permission to use, copy, modify, and distribute this software and its documentation for educational,
research, and not-for-profit purposes, without fee and without a signed licensing agreement, is
hereby granted, provided that the above copyright notice, this paragraph and the following two
paragraphs appear in all copies, modifications, and distributions. Contact The Office of Technology
Licensing, UC Berkeley, 2150 Shattuck Avenue, Suite 510, Berkeley, CA 94720-1620, (510) 643-
7201, otl@berkeley.edu, http://ipira.berkeley.edu/industry-info for commercial licensing opportunities.

IN NO EVENT SHALL REGENTS BE LIABLE TO ANY PARTY FOR DIRECT, INDIRECT, SPECIAL,
INCIDENTAL, OR CONSEQUENTIAL DAMAGES, INCLUDING LOST PROFITS, ARISING OUT OF
THE USE OF THIS SOFTWARE AND ITS DOCUMENTATION, EVEN IF REGENTS HAS BEEN
ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

REGENTS SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE. THE SOFTWARE AND ACCOMPANYING DOCUMENTATION, IF ANY, PROVIDED
HEREUNDER IS PROVIDED "AS IS". REGENTS HAS NO OBLIGATION TO PROVIDE
MAINTENANCE, SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.

Author: Mike Danielczuk
"""

import numpy as np
import gym
import trimesh
import matplotlib.pyplot as plt

from autolab_core import Logger
from pyrender import (Scene, IntrinsicsCamera, Mesh, DirectionalLight, Viewer,
                      MetallicRoughnessMaterial, Node, OffscreenRenderer, RenderFlags)

from .physics_engine import PybulletPhysicsEngine
from .state_spaces import HeapAndCameraStateSpace

class BinHeapEnv(gym.Env):
    """ OpenAI Gym-style environment for creating object heaps in a bin. """

    def __init__(self, config):
        
        self._config = config

        # read subconfigs
        self._state_space_config = self._config['state_space']

        # initialize class variables
        self._state = None
        self._scene = None
        self._physics_engine = PybulletPhysicsEngine(urdf_cache_dir=config['urdf_cache_dir'], debug=config['debug'])
        self._state_space = HeapAndCameraStateSpace(self._physics_engine, self._state_space_config)

    @property
    def config(self):
        return self._config

    @property
    def state(self):
        return self._state  

    @property
    def camera(self):
        return self._camera

    @property
    def observation(self):
        return self.render_camera_image()

    @property
    def scene(self):
        return self._scene

    @property
    def num_objects(self):
        return self.state.num_objs

    @property
    def state_space(self):
        return self._state_space

    @property
    def obj_keys(self):
        return self.state.obj_keys

    @property
    def target_key(self):
        return self.state.metadata['target_key']

    def _reset_state_space(self):
        """ Sample a new static and dynamic state. """
        state = self._state_space.sample()
        self._state = state.heap
        self._camera = state.camera
    
    def _update_scene(self):
        # update camera
        camera = IntrinsicsCamera(self.camera.intrinsics.fx, self.camera.intrinsics.fy, 
                                  self.camera.intrinsics.cx, self.camera.intrinsics.cy)
        cn = next(iter(self._scene.get_nodes(name=self.camera.frame)))
        cn.camera = camera
        pose_m = self.camera.pose.matrix.copy()
        pose_m[:,1:3] *= -1.0
        cn.matrix = pose_m
        self._scene.main_camera_node = cn

        # update workspace
        for obj_key in self.state.workspace_keys:
            next(iter(self._scene.get_nodes(name=obj_key))).matrix = self.state[obj_key].pose.matrix

        # update object
        for obj_key in self.state.obj_keys:
            next(iter(self._scene.get_nodes(name=obj_key))).matrix = self.state[obj_key].pose.matrix

    def _reset_scene(self, scale_factor=1.0):
        """ Resets the scene.

        Parameters
        ----------
        scale_factor : float
            optional scale factor to apply to the image dimensions
        """
        # delete scene
        if self._scene is not None:
            self._scene.clear()
            del self._scene

        # create scene
        scene = Scene()

        # setup camera
        camera = IntrinsicsCamera(self.camera.intrinsics.fx, self.camera.intrinsics.fy, 
                                  self.camera.intrinsics.cx, self.camera.intrinsics.cy)
        pose_m = self.camera.pose.matrix.copy()
        pose_m[:,1:3] *= -1.0
        scene.add(camera, pose=pose_m, name=self.camera.frame)
        scene.main_camera_node = next(iter(scene.get_nodes(name=self.camera.frame)))

        material = MetallicRoughnessMaterial(
            baseColorFactor=np.array([1, 1, 1, 1.0]),
            metallicFactor=0.2,
            roughnessFactor=0.8
        )

        # add workspace objects
        for obj_key in self.state.workspace_keys:
            obj_state = self.state[obj_key]
            obj_mesh = Mesh.from_trimesh(obj_state.mesh, material=material)
            T_obj_world = obj_state.pose.matrix
            scene.add(obj_mesh, pose=T_obj_world, name=obj_key)

        # add scene objects
        for obj_key in self.state.obj_keys:
            obj_state = self.state[obj_key]
            obj_mesh = Mesh.from_trimesh(obj_state.mesh, material=material)
            T_obj_world = obj_state.pose.matrix
            scene.add(obj_mesh, pose=T_obj_world, name=obj_key)

        # add light (for color rendering)
        light = DirectionalLight(color=np.ones(3), intensity=1.0)
        scene.add(light, pose=np.eye(4))
        ray_light_nodes = self._create_raymond_lights()
        [scene.add_node(rln) for rln in ray_light_nodes]

        self._scene = scene

    def reset_camera(self):
        """ Resets only the camera.
        Useful for generating image data for multiple camera views
        """
        self._camera = self.state_space.camera.sample()
        self._update_scene()     

    def reset(self):
        """ Reset the environment. """

        # reset state space
        self._reset_state_space()

        # reset scene
        self._reset_scene()

    def view_3d_scene(self):
        """ Render the scene in a 3D viewer.
        """
        if self.state is None or self.camera is None:
            raise ValueError('Cannot render 3D scene before state is set! You can set the state with the reset() function')

        Viewer(self.scene, use_raymond_lighting=True)

    def render_camera_image(self, color=True):
        """ Render the camera image for the current scene. """
        renderer = OffscreenRenderer(self.camera.width, self.camera.height)
        flags = RenderFlags.NONE if color else RenderFlags.DEPTH_ONLY
        image = renderer.render(self._scene, flags=flags)
        renderer.delete()
        return image
    
    def render_target_image(self, color=True):
        """ Render the target image for the current scene. """
        renderer = OffscreenRenderer(self.camera.width, self.camera.height)
        flags = RenderFlags.NONE if color else RenderFlags.DEPTH_ONLY
        
        # Hide all meshes
        for mn in self._scene.mesh_nodes:
            mn.mesh.is_visible = False

        # Show target mesh
        target_node = next(iter(self._scene.get_nodes(name=self.target_key)))
        target_node.mesh.is_visible = True

        image = renderer.render(self._scene, flags=flags)
        renderer.delete()

        # Show all meshes
        for mn in self._scene.mesh_nodes:
            mn.mesh.is_visible = True
            
        return image
    
    def render_segmentation_images(self):
        """Renders segmentation masks (modal and amodal) for each object in the state.
        """

        full_depth = self.render_camera_image(color=False)
        modal_data = np.zeros((full_depth.shape[0], full_depth.shape[1], len(self.obj_keys)), dtype=np.uint8)
        amodal_data = np.zeros((full_depth.shape[0], full_depth.shape[1], len(self.obj_keys)), dtype=np.uint8)
        renderer = OffscreenRenderer(self.camera.width, self.camera.height)
        flags = RenderFlags.DEPTH_ONLY

        # Hide all meshes
        obj_mesh_nodes = [next(iter(self._scene.get_nodes(name=k))) for k in self.obj_keys]
        for mn in self._scene.mesh_nodes:
            mn.mesh.is_visible = False

        for i, node in enumerate(obj_mesh_nodes):
            node.mesh.is_visible = True

            depth = renderer.render(self._scene, flags=flags)
            amodal_mask = depth > 0.0
            modal_mask = np.logical_and(
                (np.abs(depth - full_depth) < 1e-6), full_depth > 0.0
            )
            amodal_data[amodal_mask,i] = np.iinfo(np.uint8).max
            modal_data[modal_mask,i] = np.iinfo(np.uint8).max
            node.mesh.is_visible = False

        renderer.delete()
        
        # Show all meshes
        for mn in self._scene.mesh_nodes:
            mn.mesh.is_visible = True

        return amodal_data, modal_data


    def render_target_modal_mask(self):
        """Renders segmentation masks (modal and amodal) for target object. """

        target_node = next(iter(self._scene.get_nodes(name=self.target_key)))
        target_node.mesh.is_visible = False
        bin_node = next(iter(self._scene.get_nodes(name='bin')))
        bin_node.mesh.is_visible = False

        renderer = OffscreenRenderer(self.camera.width, self.camera.height)
        full_depth = renderer.render(self._scene, flags=RenderFlags.DEPTH_ONLY)

        # Hide all meshes
        for mn in self._scene.mesh_nodes:
            mn.mesh.is_visible = False

        plane_node = next(iter(self._scene.get_nodes(name='plane')))
        plane_node.mesh.is_visible = True
        plane_depth = renderer.render(self._scene, flags=RenderFlags.DEPTH_ONLY)

        target_node.mesh.is_visible = True
        depth = renderer.render(self._scene, flags=RenderFlags.DEPTH_ONLY)
        modal_mask = depth - full_depth < 0

        renderer.delete()
        
        # Show all meshes
        for mn in self._scene.mesh_nodes:
            mn.mesh.is_visible = True

        return full_depth, depth, modal_mask, plane_depth


    def find_target_distribution_2d(self):

        # Render target object and full depth image to get offset and centroid
        full_depth, target_depth, target_modal_mask, plane_depth = self.render_target_modal_mask()
        target_inds = np.stack(np.where(plane_depth > target_depth))
        target_centroid = np.mean(target_inds, axis=1)[:,None]
        target_depth_offset = (plane_depth - target_depth)[tuple(target_inds)] 
        
        # Generate meshgrid for translations to apply
        num_x_steps = 51
        num_y_steps = 38
        x = np.linspace(0, self.camera.width-1, num=num_x_steps, dtype=np.int)
        y = np.linspace(0, self.camera.height-1, num=num_y_steps, dtype=np.int)
        grid = np.meshgrid(y, x)
        grid = np.array([grid[0].flatten(), grid[1].flatten()])
        grid -= target_centroid.astype(np.int)

        # Shift target depth and add offset to create new depth images
        shifted_target_inds = np.repeat(target_inds[None,...], grid.shape[1], axis=0) + grid[None,...].T
        shifted_target_inds = shifted_target_inds.transpose(1,0,2)

        # Make all indices negative so we avoid errors and make these indices easy to filter
        over_height = shifted_target_inds[0] >= self.camera.height
        over_width = shifted_target_inds[1] >= self.camera.width
        shifted_target_inds[0][over_height] = self.camera.height - 1 - shifted_target_inds[0][over_height]
        shifted_target_inds[1][over_width] = self.camera.width - 1 - shifted_target_inds[1][over_width]
        in_bounds_mask = np.logical_and(*(shifted_target_inds >= 0))

        shifted_target_depths = plane_depth[tuple(shifted_target_inds)] - target_depth_offset
        full_depths = full_depth[tuple(shifted_target_inds)]
        target_inds_mask = target_modal_mask[tuple(target_inds)]
        visible_shifted_target_mask = np.logical_and(shifted_target_depths < full_depths, in_bounds_mask)
        dist_im, soft_dist_im = np.zeros_like(full_depth, dtype=np.bool), np.zeros_like(full_depth, dtype=np.float)

        # First, handle case where object is fully occluded
        if not np.any(target_inds_mask):
            match_mask = np.logical_and(~np.any(visible_shifted_target_mask, axis=1)[:,None], in_bounds_mask)
            matching_target_inds = shifted_target_inds[:, match_mask]

        # Next, handle case where object is not fully occluded
        else:
            # Append shift index to shifted_target_inds
            shifted_target_inds = np.concatenate((np.repeat(np.arange(shifted_target_inds.shape[1])[None,:,None], 
                                                            shifted_target_inds.shape[2], axis=-1), 
                                                  shifted_target_inds), axis=0)

            # Mask for visible pixels and indices
            visible_target_inds = shifted_target_inds[:, visible_shifted_target_mask]
            
            # Some wizardry to get iou for each shifted target
            shifted_target_masks = np.zeros((grid.shape[1], *full_depth.shape), dtype=np.bool)
            shifted_target_masks[tuple(visible_target_inds)] = True
            intersection = shifted_target_masks[:, target_modal_mask].sum(axis=1)
            union = visible_shifted_target_mask.sum(axis=1) + target_inds_mask.sum() - intersection
            mask_ious = intersection / union

            # Get matching mask indices
            iou_thresh = min(0.9, (target_inds_mask.sum() - 2) / target_inds_mask.sum())
            iou_mask = np.logical_and((mask_ious >= iou_thresh)[:,None], in_bounds_mask)
            matching_target_inds = shifted_target_inds[1:, iou_mask]
            if not np.any(matching_target_inds):
                matching_target_inds = target_inds

        dist_im[matching_target_inds[0].flatten(), matching_target_inds[1].flatten()] = True
        np.add.at(soft_dist_im, (matching_target_inds[0].flatten(), matching_target_inds[1].flatten()), 1)
        soft_dist_im = (np.iinfo(np.uint8).max * soft_dist_im / soft_dist_im.max()).astype(np.uint8)
        return dist_im, soft_dist_im


    def _generate_rotation_matrices(self, step=np.pi/32):
        angles = np.arange(step, 2*np.pi, step)
        num_angles = len(angles)
        axes = np.tile(np.array([[1,0,0],[0,1,0],[0,0,1]]), num_angles).astype(np.float)
        angles = np.repeat(angles, 3)

        sina = np.sin(angles)
        cosa = np.cos(angles)
        M = np.zeros((len(angles), 4, 4))
        M[:, range(4), range(4)] = np.array([cosa, cosa, cosa, np.ones(len(angles))]).T
        M[:, :3, :3] += np.transpose(np.einsum('ij,kj->ikj', axes, axes) * (1.0 - cosa), (2,0,1))
        
        axes *= sina
        M[:, :3, :3] += np.transpose([[np.zeros(len(angles)), -axes[2], axes[1]], 
                                      [axes[2], np.zeros(len(angles)), -axes[0]], 
                                      [-axes[1], axes[0], np.zeros(len(angles))]], (2,0,1))

        return M

    def _create_raymond_lights(self):
        thetas = np.pi * np.array([1.0 / 6.0, 1.0 / 6.0, 1.0 / 6.0])
        phis = np.pi * np.array([0.0, 2.0 / 3.0, 4.0 / 3.0])

        nodes = []

        for phi, theta in zip(phis, thetas):
            xp = np.sin(theta) * np.cos(phi)
            yp = np.sin(theta) * np.sin(phi)
            zp = np.cos(theta)

            z = np.array([xp, yp, zp])
            z = z / np.linalg.norm(z)
            x = np.array([-z[1], z[0], 0.0])
            if np.linalg.norm(x) == 0:
                x = np.array([1.0, 0.0, 0.0])
            x = x / np.linalg.norm(x)
            y = np.cross(z, x)

            matrix = np.eye(4)
            matrix[:3,:3] = np.c_[x,y,z]
            nodes.append(Node(
                light=DirectionalLight(color=np.ones(3), intensity=1.0),
                matrix=matrix
            ))

        return nodes

    # def find_target_distribution(self, num=100):

    #     # Generate random rotation matrices and apply to current pose
    #     rand_rots = trimesh.transformations.random_rotation_matrix(num=num)
    #     rand_rots = np.concatenate((rand_rots, self._generate_rotation_matrices()), axis=0)
    #     num = len(rand_rots)
    #     curr_pose = next(iter(self._scene.get_nodes(name=self.target_key))).matrix
    #     rand_poses = np.einsum('ij,...jk->...ik', curr_pose, rand_rots)
    #     mask_ious = np.zeros(num, dtype=np.float)
    #     full_depth = np.zeros((num,self.camera.height,self.camera.width), dtype=np.float)
    #     modal_masks = np.zeros((num,self.camera.height,self.camera.width), dtype=np.bool)

    #     # Render depth images with all meshes, then hide all non-target meshes
    #     renderer = OffscreenRenderer(self.camera.width, self.camera.height)
    #     target_node = next(iter(self._scene.get_nodes(name=self.target_key)))
        
    #     orig_full_depth = renderer.render(self._scene, flags=RenderFlags.DEPTH_ONLY)
    #     for mn in self._scene.mesh_nodes:
    #         mn.mesh.is_visible = False
    #     target_node.mesh.is_visible = True
    #     depth = renderer.render(self._scene, flags=RenderFlags.DEPTH_ONLY)
    #     orig_modal_mask = np.logical_and(
    #         (np.abs(orig_full_depth - depth) < 1e-6), orig_full_depth > 0.0
    #     )

    #     for mn in self._scene.mesh_nodes:
    #         mn.mesh.is_visible = True

    #     for i,rp in enumerate(rand_poses):
    #         target_node.matrix = rp
    #         full_depth[i] = renderer.render(self._scene, flags=RenderFlags.DEPTH_ONLY)

    #     for mn in self._scene.mesh_nodes:
    #         mn.mesh.is_visible = False
    #     target_node.mesh.is_visible = True

    #     for i,rp in enumerate(rand_poses):
    #         target_node.matrix = rp
    #         depth = renderer.render(self._scene, flags=RenderFlags.DEPTH_ONLY)
    #         modal_masks[i] = np.logical_and(
    #             (np.abs(full_depth[i] - depth) < 1e-6), full_depth[i] > 0.0
    #         )
            
    #         mask_ious[i] = np.sum(np.logical_and(modal_masks[i], orig_modal_mask)) / np.sum(np.logical_or(modal_masks[i], orig_modal_mask))

    #         # if mask_ious[i] > 0.95:
    #         #     import matplotlib.pyplot as plt
    #         #     plt.figure()
    #         #     plt.imshow(modal_masks[i])
    #         #     plt.figure()
    #         #     plt.imshow(orig_modal_mask)
    #         #     plt.figure()
    #         #     plt.imshow(full_depth[i])
    #         #     plt.figure()
    #         #     plt.imshow(orig_full_depth)
    #         #     plt.show()

    #     renderer.delete()
        
    #     # Show all meshes
    #     for mn in self._scene.mesh_nodes:
    #         mn.mesh.is_visible = True

    #     return rand_poses, mask_ious

    def find_target_distribution_3d(self):

        # Render target object and full depth image to get offset and centroid
        full_depth, target_depth, target_modal_mask, plane_depth = self.render_target_modal_mask()
        target_inds = np.stack(np.where(plane_depth > target_depth))
        target_centroid = np.mean(target_inds, axis=1)[:,None]
        target_depth_offset = (plane_depth - target_depth)[tuple(target_inds)] 
        
        # Generate meshgrid for translations to apply
        num_x_steps = 51
        num_y_steps = 38
        x = np.linspace(0, self.camera.width-1, num=num_x_steps, dtype=np.int)
        y = np.linspace(0, self.camera.height-1, num=num_y_steps, dtype=np.int)
        grid = np.meshgrid(y, x)
        grid = np.array([grid[0].flatten(), grid[1].flatten()])
        grid -= target_centroid.astype(np.int)

        # Rotate target for num_rots
        num_rots = 16
        rot_angles = np.arange(num_rots) * 2 * np.pi / num_rots
        rot_mats = np.array([[np.cos(rot_angles), np.sin(rot_angles)], 
                             [-np.sin(rot_angles), np.cos(rot_angles)]])
        rotated_target_inds = np.einsum('ijk,jl->kil', rot_mats, target_inds - target_centroid)
        rotated_target_inds = (rotated_target_inds + target_centroid).astype(np.int)

        # Shift target depth and add offset to create new depth images
        shifted_target_inds = np.repeat(rotated_target_inds, grid.shape[1], axis=0) + np.tile(grid, num_rots)[None, ...].T
        shifted_target_inds = shifted_target_inds.transpose(1,0,2)

        # Make all indices negative so we avoid errors and make these indices easy to filter
        over_height = shifted_target_inds[0] >= self.camera.height
        over_width = shifted_target_inds[1] >= self.camera.width
        shifted_target_inds[0][over_height] = self.camera.height - 1 - shifted_target_inds[0][over_height]
        shifted_target_inds[1][over_width] = self.camera.width - 1 - shifted_target_inds[1][over_width]
        in_bounds_mask = np.logical_and(*(shifted_target_inds >= 0))

        shifted_target_depths = plane_depth[tuple(shifted_target_inds)] - target_depth_offset
        full_depths = full_depth[tuple(shifted_target_inds)]
        target_inds_mask = target_modal_mask[tuple(target_inds)]
        visible_shifted_target_mask = np.logical_and(shifted_target_depths < full_depths, in_bounds_mask)
        dist_im, soft_dist_im = np.zeros_like(full_depth, dtype=np.bool), np.zeros_like(full_depth, dtype=np.float)

        # First, handle case where object is fully occluded
        if not np.any(target_inds_mask):
            match_mask = np.logical_and(~np.any(visible_shifted_target_mask, axis=1)[:,None], in_bounds_mask)
            matching_target_inds = shifted_target_inds[:, match_mask]

        # Next, handle case where object is not fully occluded
        else:
            # Append shift index to shifted_target_inds
            shifted_target_inds = np.concatenate((np.repeat(np.arange(shifted_target_inds.shape[1])[None,:,None], 
                                                            shifted_target_inds.shape[2], axis=-1), 
                                                  shifted_target_inds), axis=0)

            # Mask for visible pixels and indices
            visible_target_inds = shifted_target_inds[:, visible_shifted_target_mask]
            
            # Some wizardry to get iou for each shifted target
            shifted_target_masks = np.zeros((grid.shape[1] * num_rots, *full_depth.shape), dtype=np.bool)
            shifted_target_masks[tuple(visible_target_inds)] = True
            intersection = shifted_target_masks[:, target_modal_mask].sum(axis=1)
            union = visible_shifted_target_mask.sum(axis=1) + target_inds_mask.sum() - intersection
            mask_ious = intersection / union

            # Get matching mask indices and whangle small visibility ious
            iou_thresh = min(0.9, max(target_inds_mask.sum() - 2, 1) / target_inds_mask.sum())
            iou_mask = np.logical_and((mask_ious >= iou_thresh)[:,None], in_bounds_mask)
            matching_target_inds = shifted_target_inds[1:, iou_mask]
            if not np.any(matching_target_inds):
                matching_target_inds = target_inds

        dist_im[matching_target_inds[0].flatten(), matching_target_inds[1].flatten()] = True
        np.add.at(soft_dist_im, (matching_target_inds[0].flatten(), matching_target_inds[1].flatten()), 1)
        soft_dist_im = (np.iinfo(np.uint8).max * soft_dist_im / soft_dist_im.max()).astype(np.uint8)
        return dist_im, soft_dist_im
